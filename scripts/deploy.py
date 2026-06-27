#!/usr/bin/env python3
"""
deploy.py — деплой StalZone Builder на Linux-сервер по SSH.
Требует: pip install paramiko

Использование:
  python scripts/deploy.py [--host HOST] [--port PORT] [--user USER] [--password PASSWORD]
"""
from __future__ import annotations
import argparse
import sys
import time

HOST     = '192.168.0.44'
USER     = 'admin'
PASSWORD = 'Tjsdjg444'
APP_PORT = 8080
REPO_URL = 'https://github.com/serg-lebovski/stalzonebuilder.git'
APP_DIR  = '/opt/stalzonebuilder'

def run(ssh, cmd: str, *, ignore_error: bool = False):
    print(f'  $ {cmd}')
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode(errors='replace').strip()
    err = stderr.read().decode(errors='replace').strip()
    code = stdout.channel.recv_exit_status()
    if out: print(f'    {out}')
    if err: print(f'    [stderr] {err}')
    if code != 0 and not ignore_error:
        print(f'  ✗ команда завершилась с кодом {code}')
    return code, out, err


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host',     default=HOST)
    parser.add_argument('--user',     default=USER)
    parser.add_argument('--password', default=PASSWORD)
    parser.add_argument('--port',     type=int, default=APP_PORT)
    args = parser.parse_args()

    try:
        import paramiko
    except ImportError:
        print('Устанавливаю paramiko...')
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'paramiko', '-q'])
        import paramiko

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f'\n=== Подключение к {args.user}@{args.host} ===')
    try:
        ssh.connect(args.host, username=args.user, password=args.password, timeout=15)
    except Exception as e:
        print(f'✗ Не удалось подключиться: {e}')
        sys.exit(1)
    print('✓ Подключено\n')

    # Ensure git and python3 are available
    print('=== Проверка зависимостей ===')
    for pkg in ['python3', 'git']:
        code, out, _ = run(ssh, f'which {pkg}', ignore_error=True)
        if code != 0:
            print(f'  Установка {pkg}...')
            run(ssh, 'apt-get update -q')
            run(ssh, f'apt-get install -y -q {pkg}')

    # Clone or update
    print('\n=== Обновление кода ===')
    code, _, _ = run(ssh, f'test -d {APP_DIR}/.git', ignore_error=True)
    if code == 0:
        run(ssh, f'git -C {APP_DIR} fetch origin && git -C {APP_DIR} reset --hard origin/main')
    else:
        run(ssh, f'git clone {REPO_URL} {APP_DIR}')

    # Write systemd service
    print('\n=== Установка systemd-сервиса ===')
    service = f"""[Unit]
Description=StalZone Builder Web App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory={APP_DIR}
Environment=PORT={args.port}
Environment=SERVER_MODE=1
ExecStart=/usr/bin/python3 -m app.main --server --port {args.port}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    # Write via heredoc
    service_esc = service.replace("'", "'\"'\"'")
    run(ssh, f"bash -c 'cat > /etc/systemd/system/stalzonebuilder.service' <<'SEOF'\n{service}\nSEOF")

    run(ssh, 'systemctl daemon-reload')
    run(ssh, 'systemctl enable stalzonebuilder')
    run(ssh, 'systemctl restart stalzonebuilder')

    time.sleep(3)
    print('\n=== Статус сервиса ===')
    run(ssh, 'systemctl status stalzonebuilder --no-pager -l', ignore_error=True)

    # Check open port
    code, out, _ = run(ssh, f'ss -tlnp | grep :{args.port}', ignore_error=True)

    ssh.close()

    if code == 0 or out:
        print(f'\n✓ Приложение запущено: http://{args.host}:{args.port}')
    else:
        print(f'\n? Сервис установлен. Проверьте: http://{args.host}:{args.port}')


if __name__ == '__main__':
    main()
