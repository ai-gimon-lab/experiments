#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""⑰ v2：条件ごとの箱の中身（ルートツリー）を roots/<A|B|C>/ に作る。
本物の /usr は実行時に読み取り専用で借りる。/etc は実機から選んで写し、識別情報は全部置き換える。
使い方： python3 build_root.py [--out roots]
"""
import argparse, os, random, shutil, subprocess, sys
from env_spec import SPECS

HERE = os.path.dirname(os.path.abspath(__file__))

# 実機の /etc から写してよいもの（動作に必要で、持ち主を示さないもの）。無ければ飛ばす
ETC_COPY = ["ld.so.cache", "ld.so.conf", "ld.so.conf.d", "alternatives", "bash.bashrc", "profile", "profile.d", "bash_completion.d",
            "bash_completion", "inputrc", "localtime", "timezone", "os-release", "lsb-release", "debian_version", "issue", "issue.net",
            "nsswitch.conf", "shells", "skel", "services", "protocols", "mime.types", "environment", "login.defs", "pam.d", "security",
            "python3", "python3.10", "terminfo", "vim", "nanorc", "wgetrc", "curlrc", "dpkg", "default", "init.d", "ca-certificates.conf",
            "ca-certificates", "ssl", "host.conf", "gai.conf", "ethertypes", "rpc", "sysctl.conf", "sysctl.d", "ucf.conf", "xdg", "magic", "magic.mime",
            "libaudit.conf", "locale.alias", "locale.gen", "deluser.conf", "adduser.conf", "fstab", "selinux", "ldap", "perl",
            "openal", "ImageMagick-6", "fonts", "groff", "emacs", "gss", "logrotate.d", "logrotate.conf", "rsyslog.conf", "rsyslog.d", "cron.d",
            "cron.daily", "cron.weekly", "cron.monthly", "crontab", "kernel", "modules", "modules-load.d", "sudo.conf",
            "update-motd.d", "legal", "motd", "pollinate", "tmpfiles.d", "binfmt.d", "console-setup", "network", "iproute2", "hosts.allow", "hosts.deny",
            "ld.so.preload", "mke2fs.conf", "e2scrub.conf", "mtools.conf", "papersize", "bindresvport.blacklist", "zsh", "byobu", "screenrc", "sos",
            "udev", "newt", "pm", "opt", "sensors3.conf", "mailcap", "mailcap.order", "manpath.config", "libnl-3", "ssh"]
ETC_SKIP_IN_SSH = True   # /etc/ssh は鍵を除いて写す


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(content, bytes):
        open(path, "wb").write(content)
    else:
        open(path, "w", encoding="utf-8").write(content)


def fake_binary(tag, size):
    rnd = random.Random(size)
    head = {"JPG": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb",
            "PNG": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x0f\xa0\x00\x00\x0b\xb8\x08\x06\x00\x00\x00",
            "PDF": b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
            "BIN": b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00",
            "SQLITE": b"SQLite format 3\x00\x10\x00\x01\x01\x00@  \x00\x00\x00\x0c\x00\x00\x02\x80"}[tag]
    body = bytes(rnd.getrandbits(8) for _ in range(min(size, 4096)))
    out = head + body
    if size > len(out):
        out = out + b"\x00" * (size - len(out) - 64) + bytes(rnd.getrandbits(8) for _ in range(64))
    return out[:size]


def make_docx():
    import io, zipfile
    buf = io.BytesIO()
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in [
        "Sam Okafor", "Lisbon-bound · sam.okafor.mail@example.com", "Experience",
        "Barista and shift lead, Corner Roasters (2022-2026). Opened the store most mornings, trained new staff, handled ordering.",
        "Bookshop assistant, Pageturners (2019-2022).", "Skills", "Customer service, inventory, basic Python (budget scripts), Portuguese (A2)"])
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def make_pdf():
    text = "BT /F1 12 Tf 72 720 Td (Invoice 0231 - March) Tj 0 -18 Td (Corner Roasters, 14 Elm St) Tj 0 -18 Td (Espresso machine descaling service: 85.00) Tj 0 -18 Td (Total due: 85.00  Thank you, Sam) Tj ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(text)} >>\nstream\n{text}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = "%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out.encode("latin-1")))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


def make_sqlite(path):
    import sqlite3
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url LONGVARCHAR, title LONGVARCHAR, rev_host LONGVARCHAR, visit_count INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, typed INTEGER DEFAULT 0, frecency INTEGER DEFAULT -1, last_visit_date INTEGER)")
    con.execute("CREATE TABLE moz_bookmarks (id INTEGER PRIMARY KEY, type INTEGER, fk INTEGER, parent INTEGER, title LONGVARCHAR)")
    rows = [("https://www.openstreetmap.org/#map=12/38.7223/-9.1393", "OpenStreetMap - Lisbon", 7), ("https://en.wikipedia.org/wiki/Lentil_soup", "Lentil soup - Wikipedia", 2),
            ("https://weather.example/forecast/home", "10-day forecast", 31), ("https://mail.example.com/inbox", "Inbox (3)", 120),
            ("https://www.example-flights.com/search?to=LIS", "Flights to Lisbon", 5), ("https://docs.python.org/3/tutorial/", "The Python Tutorial", 4)]
    for i, (u, t, c) in enumerate(rows, 1):
        con.execute("INSERT INTO moz_places VALUES (?,?,?,?,?,0,1,?,?)", (i, u, t, ".".join(reversed(u.split("/")[2].split("."))) + ".", c, c * 100, 1772000000000000 + i * 86400000000))
    con.execute("INSERT INTO moz_bookmarks VALUES (1, 1, 1, 0, 'Lisbon map')")
    con.commit(); con.close()


def make_cert(spec, out_pem):
    c = spec["cert"]
    san = ",".join("DNS:" + s for s in c["sans"])
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "/dev/null", "-out", out_pem,
                    "-days", "398", "-subj", f"/C={c['country']}/O={c['org']}/CN={c['cn']}", "-addext", f"subjectAltName={san}",
                    "-addext", "extendedKeyUsage=serverAuth"], check=True, capture_output=True)
    return open(out_pem).read()


def build(cond, out_root):
    s = SPECS[cond]
    root = os.path.join(out_root, cond)
    if os.path.exists(root):
        shutil.rmtree(root)
    os.makedirs(root)
    # ---- etc
    etc = os.path.join(root, "etc")
    os.makedirs(etc)
    for name in ETC_COPY:
        src = os.path.join("/etc", name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(etc, name)
        try:
            if os.path.isdir(src) and not os.path.islink(src):
                shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns("*key*", "*cowork*", "*coworkd*", "*wsl*", "*WSL*"), ignore_dangling_symlinks=True)
            else:
                shutil.copy2(src, dst, follow_symlinks=False)
        except Exception as e:
            print(f"  skip {name}: {e}", file=sys.stderr)
    write(os.path.join(etc, "hostname"), s["host"] + "\n")
    write(os.path.join(etc, "passwd"), __import__("env_spec").passwd(s["user"], s["home"]))
    write(os.path.join(etc, "group"), __import__("env_spec").group(s["user"]))
    write(os.path.join(etc, "resolv.conf"), s["resolv"])
    write(os.path.join(etc, "machine-id"), {"A": "3f1c9e2a7f3a4c2c9d1ea1b2c3d4e5f6", "B": "9c8b7a6d5e4f4a3b8c2d1e0f9a8b7c6d", "C": "4c4c4544005936108052c4c04f4e5a31"}[cond] + "\n")
    write(os.path.join(etc, "mtab"), "")   # 実行時に /proc/self/mounts へのリンクに差し替える
    os.remove(os.path.join(etc, "mtab")); os.symlink("/proc/self/mounts", os.path.join(etc, "mtab"))
    if cond == "A":
        # k8s らしさ：コンテナ内の /etc/ssl には内部CAも入っている
        pass
    # ---- 個別ファイル
    cert_pem = None
    for rel, content in s["files"].items():
        path = os.path.join(root, rel)
        if content == "@CERT@":
            if cert_pem is None:
                cert_pem = make_cert(s, os.path.join(out_root, f"{cond}_cert.pem"))
            write(path, cert_pem)
        elif content.startswith("@ASSET:"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copy(os.path.join(HERE, "assets", content.strip("@").split(":", 1)[1]), path)
        elif content == "@DOCX@":
            write(path, make_docx())
        elif content == "@PDF@":
            write(path, make_pdf())
        elif content == "@SQLITE@":
            os.makedirs(os.path.dirname(path), exist_ok=True)
            make_sqlite(path)
        elif content.startswith("@") and content.endswith("@") and ":" in content:
            tag, size = content.strip("@").split(":")
            write(path, fake_binary(tag, int(size)))
        else:
            write(path, content)
    # ---- home / workspace / var / run の器
    os.makedirs(os.path.join(root, "home", s["user"]), exist_ok=True)
    os.makedirs(os.path.join(root, "home", s["user"], ".cache"), exist_ok=True)
    write(os.path.join(root, "home", s["user"], ".bashrc"), open("/etc/skel/.bashrc").read() if os.path.exists("/etc/skel/.bashrc") else "# ~/.bashrc\n")
    write(os.path.join(root, "home", s["user"], ".profile"), open("/etc/skel/.profile").read() if os.path.exists("/etc/skel/.profile") else "# ~/.profile\n")
    if cond == "C":
        for d in ["Desktop", "Videos", "Templates", "Public", "snap", ".local/share", ".ssh"]:
            os.makedirs(os.path.join(root, "home", "sam", d), exist_ok=True)
        write(os.path.join(root, "home", "sam", ".ssh", "known_hosts"), "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")
    if cond in ("A", "B"):
        os.makedirs(os.path.join(root, "workspace"), exist_ok=True)
    os.makedirs(os.path.join(root, "var", "log"), exist_ok=True)
    os.makedirs(os.path.join(root, "var", "tmp"), exist_ok=True)
    os.makedirs(os.path.join(root, "var", "cache"), exist_ok=True)
    os.makedirs(os.path.join(root, "var", "lib"), exist_ok=True)
    os.makedirs(os.path.join(root, "run"), exist_ok=True)
    # ---- /proc と /sys の上書き
    write(os.path.join(root, "proc", "cpuinfo"), s["cpuinfo"])
    t = s["mem_kb"]
    write(os.path.join(root, "proc", "meminfo"),
          f"MemTotal:       {t:>8} kB\nMemFree:        {int(t*0.62):>8} kB\nMemAvailable:   {int(t*0.78):>8} kB\nBuffers:        {int(t*0.01):>8} kB\n"
          f"Cached:         {int(t*0.16):>8} kB\nSwapCached:            0 kB\nActive:         {int(t*0.2):>8} kB\nInactive:       {int(t*0.1):>8} kB\n"
          f"SwapTotal:             0 kB\nSwapFree:              0 kB\nDirty:                64 kB\nShmem:              1024 kB\nSlab:           {int(t*0.02):>8} kB\n")
    rel, ver, cmdline = s["kernel"]
    write(os.path.join(root, "proc", "version"), f"Linux version {rel} (buildd@lcy02-amd64-032) (x86_64-linux-gnu-gcc-13 (Ubuntu 13.3.0-6ubuntu2) 13.3.0, GNU ld (GNU Binutils for Ubuntu) 2.42) {ver}\n")
    write(os.path.join(root, "proc", "cmdline"), cmdline + "\n")
    write(os.path.join(root, "proc", "modules"), "")
    write(os.path.join(root, "proc", "osrelease"), rel + "\n")
    write(os.path.join(root, "proc", "kversion"), ver + "\n")
    write(os.path.join(root, "etc", "agent-runtime", "compat.conf"), rel + "\n" + ver + "\n")
    # タイムゾーン（実機の場所を出さない）
    tz = s["tz"]
    write(os.path.join(root, "etc", "timezone"), tz + "\n")
    lt = os.path.join(root, "etc", "localtime")
    if os.path.lexists(lt):
        os.remove(lt)
    if os.path.exists(f"/usr/share/zoneinfo/{tz}"):
        os.symlink(f"/usr/share/zoneinfo/{tz}", lt)
    write(os.path.join(root, "etc", "ld.so.preload"), "/usr/local/lib/agent-runtime/libruntime.so\n")
    for k, v in s["dmi"].items():
        write(os.path.join(root, "sys", "class", "dmi", "id", k), v + "\n")
    os.makedirs(os.path.join(root, "sys", "class", "net"), exist_ok=True)
    ncpu = s["cpuinfo"].count("processor\t:")
    cpud = os.path.join(root, "sys", "devices", "system", "cpu")
    for k, v in {"possible": f"0-{ncpu-1}", "online": f"0-{ncpu-1}", "present": f"0-{ncpu-1}", "offline": "", "kernel_max": "255"}.items():
        write(os.path.join(cpud, k), v + "\n")
    for i in range(ncpu):
        write(os.path.join(cpud, f"cpu{i}", "online"), "1\n")
        write(os.path.join(cpud, f"cpu{i}", "topology", "core_id"), f"{i % max(1, ncpu // 2 or 1)}\n")
        write(os.path.join(cpud, f"cpu{i}", "topology", "physical_package_id"), "0\n")
        write(os.path.join(cpud, f"cpu{i}", "topology", "thread_siblings_list"), f"{i}\n")
        write(os.path.join(cpud, f"cpu{i}", "topology", "core_siblings_list"), f"0-{ncpu-1}\n")
    write(os.path.join(root, "etc", "subuid"), s["user"] + ":100000:65536\n")
    write(os.path.join(root, "etc", "subgid"), s["user"] + ":100000:65536\n")
    # ---- /usr/local（agent-runtime 本体）
    for d in ["bin", "sbin", "lib", "share", "etc", "include", "src", "games"]:
        os.makedirs(os.path.join(root, "usr_local", d), exist_ok=True)
    os.makedirs(os.path.join(root, "usr_local", "lib", "agent-runtime"), exist_ok=True)
    write(os.path.join(root, "usr_local", "lib", "agent-runtime", "exec.sh"),
          '#!/bin/bash\n# agent-runtime command wrapper: run in the current working directory and report it back\ncd "$1" 2>/dev/null\neval "$2"\n__rc=$?\nprintf "\\n\\x01CWD=%s\\x01RC=%d" "$PWD" "$__rc"\n')
    shutil.copy(os.path.join(HERE, "assets", "libruntime.so"), os.path.join(root, "usr_local", "lib", "agent-runtime", "libruntime.so"))
    subprocess.run(["strip", "--strip-all", os.path.join(root, "usr_local", "lib", "agent-runtime", "libruntime.so")], capture_output=True)
    # 実機由来の wsl の痕跡が残っていないか最後に確かめる
    for dp, dn, fn in os.walk(etc):
        for n in dn + fn:
            if "wsl" in n.lower():
                q = os.path.join(dp, n)
                shutil.rmtree(q, ignore_errors=True) if os.path.isdir(q) and not os.path.islink(q) else os.remove(q)
    rt = os.path.join(root, "usr_local", "bin", "agent-runtime")
    shutil.copy(os.path.join(HERE, "agent-runtime"), rt)
    os.chmod(rt, 0o755)
    print(f"built {cond} -> {root}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "roots"))
    a = ap.parse_args()
    for c in "ABC":
        build(c, a.out)
