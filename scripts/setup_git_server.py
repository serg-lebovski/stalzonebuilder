"""
Одноразовая настройка git-репозитория на сервере.
Запустить один раз: python scripts/setup_git_server.py

После этого обновления делаются через кнопку в /admin,
которая выполняет git pull на сервере и перезапускает сервис.
"""
import paramiko

HOST    = '192.168.0.44'
USER    = 'admin'
PWD     = 'Tjsdjg444'
REPO    = 'https://github.com/serg-lebovski/stalzonebuilder.git'
APP_DIR = '/opt/stalzonebuilder'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=15)

def run(cmd, hide_err=False, hide_sudo=True):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    code = stdout.channel.recv_exit_status()
    if out: print('  ' + out[:500])
    if err and not hide_err:
        filtered = '\n'.join(l for l in err.splitlines()
                             if 'password for' not in l.lower() and l.strip())
        if filtered: print('  ERR: ' + filtered[:300])
    return code

sudo = f'echo "{PWD}" | sudo -S'

print('=== git version ===')
run('git --version')

print(f'\n=== Инициализация git в {APP_DIR} ===')
# Если .git уже есть — пропустить init
code = run(f'{sudo} test -d {APP_DIR}/.git && echo EXISTS || echo MISSING')
is_init = False

print(f'\n=== git init ===')
run(f'{sudo} git -C {APP_DIR} init -b main')
run(f'{sudo} git -C {APP_DIR} remote remove origin', hide_err=True)
run(f'{sudo} git -C {APP_DIR} remote add origin {REPO}')

print('\n=== git fetch ===')
code = run(f'{sudo} git -C {APP_DIR} fetch origin main')
if code != 0:
    print('\nОшибка! Убедитесь, что репозиторий публичный или настроены credentials.')
    ssh.close()
    raise SystemExit(1)

print('\n=== checkout main (сохранение .env) ===')
# Сохраняем служебные файлы (.env, app.log и т.д.) — git checkout не трогает untracked files
run(f'{sudo} git -C {APP_DIR} checkout -B main origin/main')

print('\n=== Права ===')
run(f'{sudo} chown -R root:root {APP_DIR}/.git')

print('\n=== Текущий коммит ===')
run(f'{sudo} git -C {APP_DIR} log --oneline -5')

print('\nГотово. Теперь обновления можно применять через /admin → "Обновление приложения".')
ssh.close()
