#!/usr/bin/env python3
"""
deploy.py — деплой StalZone Builder на Linux-сервер по SSH.
Требует: pip install paramiko

Использование:
  python scripts/deploy.py
"""
from __future__ import annotations
import sys
import time

HOST     = '192.168.0.44'
USER     = 'admin'
PASSWORD = 'Tjsdjg444'

def run(ssh, cmd: str, ignore_error: bool = False, get_out: bool = False):
    print(f'  $ {cmd[:100]}')
    _, stdout, stderr = ssh.exec_command(cmd, timeout=300)
    out = stdout.read().decode(errors='replace').strip()
    err = stderr.read().decode(errors='replace').strip()
    code = stdout.channel.recv_exit_status()
    if out and len(out) < 500: print(f'    {out}')
    if err and not ignore_error: print(f'    [!] {err[:200]}')
    if code != 0 and not ignore_error:
        print(f'  ✗ код {code}')
    return (code, out) if get_out else code


def main():
    try:
        import paramiko
    except ImportError:
        print('Устанавливаю paramiko...')
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'paramiko', '-q'])
        import paramiko

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f'\n=== Подключение к {USER}@{HOST} ===')
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    print('OK Подключено\n')

    # Upload setup.sh and run it
    print('=== Загрузка setup.sh ===')
    with open('scripts/setup.sh', 'r', encoding='utf-8') as f:
        content = f.read()

    sftp = ssh.open_sftp()
    with sftp.file('/tmp/setup_szb.sh', 'w') as f:
        f.write(content)
    sftp.close()

    print('=== Запуск установки (может занять 1-3 минуты) ===')
    # Try with sudo if running as non-root
    _, out = run(ssh, f'echo "{PASSWORD}" | sudo -S bash /tmp/setup_szb.sh 2>&1', get_out=True)
    print('\n' + out)

    ssh.close()


if __name__ == '__main__':
    main()
