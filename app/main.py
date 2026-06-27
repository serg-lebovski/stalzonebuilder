from __future__ import annotations
import sys
import os
import webbrowser
import threading
import time
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('main')


def main():
    parser = argparse.ArgumentParser(description='StalZone Builder')
    parser.add_argument('--server', action='store_true',
                        help='Режим сервера: bind 0.0.0.0, не открывать браузер')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--host', default=None)
    args = parser.parse_args()

    server_mode = args.server or os.environ.get('SERVER_MODE', '').lower() in ('1', 'true', 'yes')
    host = args.host or ('0.0.0.0' if server_mode else '127.0.0.1')
    port = args.port or int(os.environ.get('PORT', 0))

    # Init DB if configured
    db_url = os.environ.get('DB_URL', '')
    if db_url:
        log.info('Подключение к PostgreSQL...')
        try:
            from . import db
            db.init_db()
            log.info('База данных инициализирована.')
        except Exception as e:
            log.error(f'Ошибка подключения к БД: {e}')
            sys.exit(1)

    # Start catalog updater (background thread)
    from .updater import start_background_updater, get_catalog
    start_background_updater()

    # Wait for first catalog load (up to 60s)
    log.info('Ожидание загрузки каталога...')
    for _ in range(120):
        if get_catalog() is not None:
            break
        time.sleep(0.5)
    else:
        log.error('Каталог не загрузился за 60 секунд. Проверьте интернет-соединение.')
        sys.exit(1)

    from .server import run, find_free_port
    if port == 0:
        port = find_free_port(8080)

    if not server_mode:
        url = f'http://127.0.0.1:{port}'
        def open_browser():
            time.sleep(0.8)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()
        log.info(f'Открываю браузер: {url}')

    run(host=host, port=port)


if __name__ == '__main__':
    main()
