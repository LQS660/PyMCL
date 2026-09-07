# -*- coding: utf-8 -*-
"""Deploy feedback_hub via SSH/SFTP. Usage: python _deploy_feedback.py host port user password"""

from __future__ import annotations

import io
import posixpath
import secrets
import sys
import time
from pathlib import Path

import paramiko

LOCAL = Path(__file__).resolve().parent
PKG = LOCAL / "feedback_hub"
REMOTE_ROOT = "/vol1/1000/pymcl-feedback"
REMOTE_PKG = REMOTE_ROOT + "/feedback_hub"
INGEST_PORT = 18788
UI_PORT = 18789

UPLOAD_NAMES = [
    "__init__.py",
    "__main__.py",
    "server.py",
    "dashboard.html",
    "README.md",
    "start.sh",
    "stop.sh",
    ".env.example",
]


def run(ssh, cmd, timeout=60):
    print(">>", cmd)
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(err.rstrip())
    return code, out, err


def mkdir_p(sftp, path):
    parts = []
    cur = path
    while cur not in ("", "/"):
        parts.append(cur)
        cur = posixpath.dirname(cur)
    for item in reversed(parts):
        try:
            sftp.stat(item)
        except FileNotFoundError:
            sftp.mkdir(item)


def put_text(sftp, path, text):
    bio = io.BytesIO(text.encode("utf-8"))
    sftp.putfo(bio, path)


def main():
    host, port, user, password = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    token = secrets.token_urlsafe(18)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("connecting %s@%s:%s" % (user, host, port))
    client.connect(
        hostname=host, port=port, username=user, password=password,
        timeout=20, allow_agent=False, look_for_keys=False,
    )
    code, out, _ = run(client, "uname -a; id; python3 --version; mkdir -p %s/data" % REMOTE_PKG)
    if code != 0:
        raise SystemExit("remote probe failed")

    sftp = client.open_sftp()
    mkdir_p(sftp, REMOTE_PKG + "/data")
    for name in UPLOAD_NAMES:
        src = PKG / name
        dst = REMOTE_PKG + "/" + name
        print("put", src.name, "->", dst)
        sftp.put(str(src), dst)
    env = (
        "BIND=0.0.0.0\n"
        "INGEST_BIND=0.0.0.0\n"
        "INGEST_PORT=%s\n"
        "UI_BIND=0.0.0.0\n"
        "UI_PORT=%s\n"
        "ADMIN_TOKEN=%s\n"
        "RATE_PER_MIN=30\n"
        "RATE_PER_DAY=400\n"
        "MACHINE_TTL=90\n"
        % (INGEST_PORT, UI_PORT, token)
    )
    put_text(sftp, REMOTE_PKG + "/.env", env)
    wrapper = (
        "#!/bin/sh\n"
        "cd %s\n"
        "exec sh feedback_hub/start.sh\n" % REMOTE_ROOT
    )
    put_text(sftp, REMOTE_ROOT + "/start.sh", wrapper)
    put_text(sftp, REMOTE_ROOT + "/stop.sh", "#!/bin/sh\ncd %s\nexec sh feedback_hub/stop.sh\n" % REMOTE_ROOT)
    sftp.chmod(REMOTE_PKG + "/start.sh", 0o755)
    sftp.chmod(REMOTE_PKG + "/stop.sh", 0o755)
    sftp.chmod(REMOTE_ROOT + "/start.sh", 0o755)
    sftp.chmod(REMOTE_ROOT + "/stop.sh", 0o755)
    sftp.close()

    run(client, "sh %s/stop.sh || true" % REMOTE_ROOT)
    time.sleep(0.5)
    code, _, _ = run(client, "sh %s/start.sh" % REMOTE_ROOT)
    if code != 0:
        run(client, "tail -n 50 %s/data/hub.log" % REMOTE_PKG)
        raise SystemExit("start failed")
    time.sleep(1.5)
    run(client, "ss -lntp 2>/dev/null | grep -E '%s|%s' || netstat -lntp 2>/dev/null | grep -E '%s|%s' || true" % (
        INGEST_PORT, UI_PORT, INGEST_PORT, UI_PORT))
    run(client, "python3 - <<'PY'\n"
        "import json,urllib.request\n"
        "for url in ('http://127.0.0.1:%s/health','http://127.0.0.1:%s/health'):\n"
        "    raw=urllib.request.urlopen(url,timeout=5).read().decode()\n"
        "    print(url, raw)\n"
        "req=urllib.request.Request('http://127.0.0.1:%s/')\n"
        "try:\n"
        "    urllib.request.urlopen(req,timeout=5)\n"
        "    print('INGEST_ROOT_SHOULD_404')\n"
        "except Exception as e:\n"
        "    print('ingest_root', type(e).__name__)\n"
        "html=urllib.request.urlopen('http://127.0.0.1:%s/?token=%s',timeout=5).read().decode('utf-8','replace')\n"
        "print('ui_html', 'EventSource' in html, len(html))\n"
        "PY" % (INGEST_PORT, UI_PORT, INGEST_PORT, UI_PORT, token))
    print("ADMIN_TOKEN=" + token)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
