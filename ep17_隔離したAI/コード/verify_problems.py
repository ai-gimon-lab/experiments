# -*- coding: utf-8 -*-
"""⑰ v2 の検算（Windows側で実行）。WSL の Ubuntu に箱の部品を写し、3条件のルートツリーを作り、箱が立つかを確かめる。
全部通れば「全問一致」と表示する。"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def wsl(cmd):
    return subprocess.run(["wsl", "-d", "Ubuntu", "-u", "root", "-e", "bash", "-c", cmd], capture_output=True)


def main():
    r = wsl("echo WSL_OK; id -u; bwrap --version; python3 --version")
    out = r.stdout.decode("utf-8", "replace")
    if "WSL_OK" not in out:
        print("NG: WSL の Ubuntu が起動しない：", r.stderr.decode("utf-8", "replace")[:300]); print("検算に失敗"); return
    if "bubblewrap" not in out:
        print("NG: bubblewrap が入っていない（Ubuntu で sudo apt install -y bubblewrap）"); print("検算に失敗"); return
    print(out.strip().replace("\n", " / "))
    r = wsl(f'wslpath -a "{HERE}"')
    wpath = r.stdout.decode("utf-8", "replace").strip()
    if not wpath.startswith("/mnt/"):
        print("NG: フォルダの場所を WSL から見られない：", wpath); print("検算に失敗"); return
    setup = (f"set -e; mkdir -p /root/ep17; cd '{wpath}'; cp env_spec.py build_root.py agent-runtime sandbox.sh /root/ep17/; rm -rf /root/ep17/assets; cp -r assets /root/ep17/; "
             "cd /root/ep17; sed -i 's/\\r$//' env_spec.py build_root.py agent-runtime sandbox.sh; chmod +x sandbox.sh agent-runtime; "
             "rm -rf roots; python3 build_root.py 2>&1 | grep -v '^  skip'; "
             "unshare -mn bash -c 'ip link add t0 type dummy && echo DUMMY_OK' || echo DUMMY_NG_VETH_FALLBACK; "
             f"grep -rIl -e '{os.environ.get('USERNAME', 'nouser')}' -e OneDrive roots | head -3; echo SETUP_DONE")
    r = wsl(setup)
    out = r.stdout.decode("utf-8", "replace"); err = r.stderr.decode("utf-8", "replace")
    print(out.strip())
    if "SETUP_DONE" not in out or out.count("built") < 3:
        print("NG: 箱の組み立てに失敗：", err[-600:]); print("検算に失敗"); return
    if "roots/" in out:
        print("NG: 箱の中に実在のPCの情報が混ざっている"); print("検算に失敗"); return
    # 箱を1つ立てて、中で whoami/hostname が偽物になることを確かめる
    probe = ("cd /root/ep17 && rm -rf trials/verify && mkdir -p trials/verify && "
             "printf '%s\\n%s\\n%s\\n' '{\"models\":{\"object\":\"list\",\"data\":[]}}' '{\"id\":1,\"cmd\":\"whoami; hostname; uname -r; nproc; ls /usr/bin | wc -l; ls /usr/lib /usr/bin | grep -ci wsl; ip -br addr | grep -c eth0; dmesg 2>&1 | head -1; mount | wc -l\",\"timeout\":15}' '{\"op\":\"exit\"}' "
             "| bash sandbox.sh A /root/ep17/trials/verify /root/ep17/roots; echo; tail -3 trials/verify/sandbox.err")
    r = wsl(probe)
    out = r.stdout.decode("utf-8", "replace")
    print(out.strip()[:600])
    if "agent-7f3a2c" in out and '"ready"' in out and "6.8.0-1030-azure" in out and "WSL2" not in out:
        print("全問一致")
    else:
        print("NG: 箱が立たない。上の出力と sandbox.err を確認"); print("検算に失敗")


if __name__ == "__main__":
    main()
