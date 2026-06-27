from __future__ import annotations
import json
import os
import sys
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import inventory as inv_store
from .calc import calculate_build
from .optimizer import optimize, get_presets
from .models import Catalog


def _web_dir() -> pathlib.Path:
    if getattr(sys, 'frozen', False):
        base = pathlib.Path(sys._MEIPASS)
    else:
        base = pathlib.Path(__file__).parent.parent
    return base / 'web'


MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css':  'text/css; charset=utf-8',
    '.js':   'application/javascript; charset=utf-8',
    '.png':  'image/png',
    '.ico':  'image/x-icon',
    '.json': 'application/json',
}


def make_handler(catalog: Catalog):

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # silence default access log

        def _send_json(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, msg, status=400):
            self._send_json({'error': msg}, status)

        def _read_body(self) -> dict:
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode('utf-8'))

        def _serve_static(self, path: str):
            web = _web_dir()
            clean = path.lstrip('/')
            if not clean or clean == '':
                clean = 'index.html'
            fpath = web / clean
            if not fpath.exists() or not fpath.is_file():
                fpath = web / 'index.html'
            if not fpath.exists():
                self.send_response(404)
                self.end_headers()
                return
            ext = fpath.suffix.lower()
            mime = MIME.get(ext, 'application/octet-stream')
            data = fpath.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == '/api/catalog':
                self._send_json(catalog.to_dict())

            elif path == '/api/inventory':
                self._send_json(inv_store.load())

            elif path == '/api/presets':
                self._send_json(get_presets(catalog.stat_defs))

            elif path == '/api/status':
                self._send_json({
                    'ok': True,
                    'artifacts': len(catalog.artifacts),
                    'containers': len(catalog.containers),
                    'armors': len(catalog.armors),
                })

            else:
                self._serve_static(path)

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == '/api/inventory':
                try:
                    body = self._read_body()
                    inv_store.save(body)
                    self._send_json({'ok': True})
                except Exception as e:
                    self._send_error(str(e))

            elif path == '/api/calc':
                try:
                    body = self._read_body()
                    armor_id    = body.get('armor_id')
                    cont_id     = body.get('container_id')
                    art_ids     = body.get('artifact_ids', [])
                    mode        = body.get('mode', 'avg')
                    max_hp      = float(body.get('max_hp', 100.0))

                    art_by_id   = {a.id: a for a in catalog.artifacts}
                    cont_by_id  = {c.id: c for c in catalog.containers}
                    arm_by_id   = {a.id: a for a in catalog.armors}

                    armor     = arm_by_id.get(armor_id)    if armor_id  else None
                    container = cont_by_id.get(cont_id)    if cont_id   else None
                    artifacts = [art_by_id[i] for i in art_ids if i in art_by_id]

                    result = calculate_build(armor, container, artifacts,
                                             catalog.stat_defs, mode, max_hp)
                    self._send_json(result)
                except Exception as e:
                    self._send_error(str(e))

            elif path == '/api/optimize':
                try:
                    body = self._read_body()
                    inv = body.get('inventory', {})
                    weights  = body.get('weights', {})
                    mode     = body.get('mode', 'avg')
                    max_hp   = float(body.get('max_hp', 100.0))
                    top_n    = int(body.get('top_n', 5))

                    results = optimize(
                        catalog=catalog,
                        inv_artifact_ids=inv.get('artifact_ids', []),
                        inv_container_ids=inv.get('container_ids', []),
                        inv_armor_ids=inv.get('armor_ids', []),
                        goal_weights=weights,
                        mode=mode,
                        max_hp=max_hp,
                        top_n=top_n,
                    )
                    self._send_json(results)
                except Exception as e:
                    self._send_error(str(e))

            else:
                self._send_error('Not found', 404)

    return Handler


def find_free_port(start: int = 8080, attempts: int = 20) -> int:
    import socket
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                continue
    return start


def run(catalog: Catalog, host: str = '127.0.0.1', port: int = 0) -> int:
    if port == 0:
        port = find_free_port(8080)
    handler = make_handler(catalog)
    server = ThreadingHTTPServer((host, port), handler)
    print(f'Сервер запущен: http://{host}:{port}')
    server.serve_forever()
    return port
