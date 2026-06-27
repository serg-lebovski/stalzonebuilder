from __future__ import annotations
import sys
import os
import webbrowser
import threading
import time
import argparse

from .data_loader import load_catalog
from . import server as srv


def main():
    parser = argparse.ArgumentParser(description='StalZone Builder')
    parser.add_argument('--server', action='store_true',
                        help='Server mode: bind to 0.0.0.0, do not open browser')
    parser.add_argument('--port', type=int, default=0,
                        help='Port to listen on (default: auto)')
    parser.add_argument('--host', default=None,
                        help='Host to bind to (default: 127.0.0.1 or 0.0.0.0 in server mode)')
    parser.add_argument('--max-hp', type=float, default=100.0,
                        help='Base max HP for Effective HP formula (default: 100)')
    args = parser.parse_args()

    server_mode = args.server or os.environ.get('SERVER_MODE', '').lower() in ('1', 'true', 'yes')
    host = args.host or ('0.0.0.0' if server_mode else '127.0.0.1')
    port = args.port or int(os.environ.get('PORT', 0))

    try:
        catalog = load_catalog()
    except ConnectionError as e:
        print(f'\nОШИБКА: {e}')
        print('Проверьте подключение к интернету и перезапустите приложение.')
        if not server_mode:
            # Show error page in browser
            _show_error_page(str(e))
        sys.exit(1)

    if port == 0:
        port = srv.find_free_port(8080)

    url = f'http://127.0.0.1:{port}' if host == '0.0.0.0' else f'http://{host}:{port}'

    if not server_mode:
        # Open browser slightly after server starts
        def open_browser():
            time.sleep(0.8)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()
        print(f'Открываю браузер: {url}')
    else:
        print(f'Сервер запущен: http://{host}:{port}')
        print('Нажмите Ctrl+C для остановки.')

    srv.run(catalog, host=host, port=port)


def _show_error_page(msg: str):
    """Write a minimal error HTML and open it in browser."""
    import pathlib, tempfile
    html = f"""<!DOCTYPE html><html lang="ru"><body style="background:#0f0f1a;color:#e0e0e0;font-family:sans-serif;padding:40px">
<h1 style="color:#ef5350">Ошибка загрузки данных</h1>
<p>{msg}</p>
<p>Проверьте подключение к интернету и перезапустите приложение.</p>
</body></html>"""
    tmp = pathlib.Path(tempfile.gettempdir()) / 'stalzone_error.html'
    tmp.write_text(html, encoding='utf-8')
    webbrowser.open(tmp.as_uri())


if __name__ == '__main__':
    main()
