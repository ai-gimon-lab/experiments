#!/bin/bash
# ⑰ v2：1試行ぶんの箱を立ち上げる。制御は標準入出力（JSON 1行ずつ）。
# 使い方： bash sandbox.sh <A|B|C> <trialdir> <rootsdir>
#   root で呼ばれれば unshare -mn、一般ユーザーなら unshare -Urmn で自分を包み直してから本体へ進む。
set -e
COND="$1"; T="$2"; ROOTS="$3"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$SANDBOX_INNER" ]; then
  mkdir -p "$T"
  if [ "$(id -u)" = "0" ]; then
    exec env SANDBOX_INNER=1 unshare -mn bash "$0" "$@" 2>"$T/sandbox.err"
  else
    exec env SANDBOX_INNER=1 unshare -Urmn bash "$0" "$@" 2>"$T/sandbox.err"
  fi
fi

read -r HOST IP PREFIX GW MAC USERNAME HOME_DIR CWD < <(python3 -c "
import sys; sys.path.insert(0, '$HERE')
from env_spec import SPECS
s = SPECS['$COND']; print(s['host'], s['ip'], s['prefix'], s['gw'], s['mac'], s['user'], s['home'], s['cwd'])")

# ---- ネットワーク（この名前空間だけ。外には出られない）
ip link set lo up
if ! ip link add eth0 type dummy 2>/dev/null; then
  # dummy が無い環境では veth で代用し、相方は別の名前空間へ逃がす
  ip link add eth0 type veth peer name veth1
  mkdir -p /var/run/netns 2>/dev/null || true
  mount -t tmpfs tmpfs /var/run/netns 2>/dev/null || true
  if ip netns add peerns 2>/dev/null; then
    ip link set veth1 netns peerns
    ip -n peerns link set veth1 up 2>/dev/null || true
  else
    ip link set veth1 up
  fi
fi
ip link set eth0 address "$MAC"
ip addr add "$IP/$PREFIX" dev eth0
ip link set eth0 up
ip route add default via "$GW" dev eth0 2>/dev/null || true

# ---- 箱の中身を RAM 上に写す（mountinfo に実機のパスを出さないため）
M="$T/mnt"
mkdir -p "$M"
mount -t tmpfs -o size=256m tmpfs "$M"
cp -a "$ROOTS/$COND/." "$M/"
TODAY="$(date -u +%Y-%m-%d)"
grep -rl "@DATE@" "$M/workspace" "$M/var/log" "$M/home" 2>/dev/null | while read -r f; do sed -i "s/@DATE@/$TODAY/g" "$f"; done
mkdir -p "$M/run/agent-runtime" "$M/tmp"
if [ "$(id -u)" = "0" ]; then chown -R 1000:1000 "$M/home" "$M/workspace" "$M/var" "$M/run" "$M/tmp" 2>/dev/null || true; fi

# ---- 環境変数
ENVARGS=()
while IFS='=' read -r k v; do ENVARGS+=(--setenv "$k" "$v"); done < <(python3 -c "
import sys; sys.path.insert(0, '$HERE')
from env_spec import SPECS
for k, v in SPECS['$COND']['env'].items(): print(f'{k}={v}')")

# /usr は本物を読み取り専用で借りる。ただし名前に wsl を含むもの（WSL の付属品）は見せない
# まず overlay で「wsl を消した /usr」を作る。できなければ項目ごとの bind で代用
BINDS=()
mkdir -p "$M/usr" "$M/ovl/up" "$M/ovl/work"
USR_OVL=0
if ( cd "$M/ovl" && mount -t overlay overlay -o lowerdir=/usr,upperdir=up,workdir=work "$M/usr" ) 2>/dev/null; then
  USR_OVL=1
  for e in "$M"/usr/lib/*wsl* "$M"/usr/bin/*wsl* "$M"/usr/share/*wsl* "$M"/usr/lib/*/*wsl*; do [ -e "$e" ] || [ -L "$e" ] && rm -rf "$e"; done
  BINDS+=(--ro-bind "$M/usr" /usr)
else
  BINDS+=(--tmpfs /usr)
  bind_filtered() {   # $1=元 $2=先
    local e name tgt
    for e in "$1"/* "$1"/.[!.]*; do
      [ -e "$e" ] || [ -L "$e" ] || continue
      name="$(basename "$e")"
      case "$name" in *wsl*|*WSL*) continue;; esac
      if [ -L "$e" ]; then tgt="$(readlink "$e")"; BINDS+=(--symlink "$tgt" "$2/$name")
      else BINDS+=(--ro-bind "$e" "$2/$name"); fi
    done
  }
  for d in /usr/*; do
    name="$(basename "$d")"
    case "$name" in local|lib|bin|share|*wsl*) continue;; esac
    if [ -L "$d" ]; then BINDS+=(--symlink "$(readlink "$d")" "/usr/$name"); else BINDS+=(--ro-bind "$d" "/usr/$name"); fi
  done
  for d in lib bin share; do
    if [ -L "/usr/$d" ]; then BINDS+=(--symlink "$(readlink "/usr/$d")" "/usr/$d"); else BINDS+=(--dir "/usr/$d"); bind_filtered "/usr/$d" "/usr/$d"; fi
  done
fi
BINDS+=(--symlink usr/bin /bin --symlink usr/sbin /sbin --symlink usr/lib /lib --symlink usr/lib64 /lib64
       --ro-bind "$M/usr_local" /usr/local
       --bind "$M/etc" /etc
       --proc /proc --dev /dev --perms 1777 --tmpfs /tmp --perms 1777 --tmpfs /dev/shm --tmpfs /run --bind "$M/run/agent-runtime" /run/agent-runtime
       --bind "$M/home" /home --bind "$M/var" /var
       --dir /root --dir /opt --dir /mnt --dir /srv --dir /media --dir /boot)
for l in lib32 libx32; do [ -e "/usr/$l" ] && BINDS+=(--symlink "usr/$l" "/$l"); done
# /proc の一部を条件の中身で上書き（実機にその項目があるものだけ）
for pair in cpuinfo:/proc/cpuinfo meminfo:/proc/meminfo version:/proc/version cmdline:/proc/cmdline modules:/proc/modules osrelease:/proc/sys/kernel/osrelease kversion:/proc/sys/kernel/version; do
  src="${pair%%:*}"; dst="${pair#*:}"
  [ -e "$dst" ] && BINDS+=(--ro-bind "$M/proc/$src" "$dst")
done
# /sys は最小限（実機の装置情報を見せない）
BINDS+=(--tmpfs /sys --ro-bind "$M/sys/class" /sys/class --ro-bind "$M/sys/devices" /sys/devices --dir /sys/kernel --dir /sys/fs --dir /sys/module --dir /sys/bus --dir /sys/block --dir /sys/firmware)
if [ -d "$M/workspace" ]; then BINDS+=(--bind "$M/workspace" /workspace); fi

if [ "$(id -u)" = "0" ]; then sysctl -q -w kernel.dmesg_restrict=1 2>/dev/null || true; fi
CPUS="0-1"
if [ "$(id -u)" = "0" ]; then
  # 本物の root：ユーザー名前空間は作らず、箱の中で一般ユーザー(1000)に落とす。システムの所有者は root のまま
  exec taskset -c "$CPUS" bwrap "${BINDS[@]}" \
    --unshare-pid --unshare-uts --unshare-ipc --unshare-cgroup \
    --hostname "$HOST" --as-pid-1 --die-with-parent --clearenv "${ENVARGS[@]}" --setenv PWD "$CWD" --chdir "$CWD" \
    /usr/bin/setpriv --reuid=1000 --regid=1000 --clear-groups --no-new-privs --inh-caps=-all /usr/local/bin/agent-runtime 2>/dev/null
else
  exec taskset -c "$CPUS" bwrap "${BINDS[@]}" \
    --unshare-user --uid 1000 --gid 1000 --unshare-pid --unshare-uts --unshare-ipc --unshare-cgroup \
    --hostname "$HOST" --as-pid-1 --die-with-parent --clearenv "${ENVARGS[@]}" --setenv PWD "$CWD" --chdir "$CWD" \
    /usr/local/bin/agent-runtime 2>/dev/null
fi
