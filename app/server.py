from __future__ import annotations
import json
import os
import sys
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs

from . import db
from .calc import calculate_build
from .optimizer import optimize, get_presets
from .updater import get_catalog, force_update, last_update_ts
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

USE_DB = bool(os.environ.get('DB_URL', ''))


def make_handler():

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        # ── helpers ────────────────────────────────────────────────────────

        def _send_json(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, msg, status=400):
            self._send_json({'error': msg}, status)

        def _send_redirect(self, location: str):
            self.send_response(302)
            self.send_header('Location', location)
            self.end_headers()

        def _read_body(self) -> dict:
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode('utf-8'))

        def _read_form(self) -> dict:
            from urllib.parse import parse_qs
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length).decode('utf-8') if length else ''
            return {k: v[0] for k, v in parse_qs(raw).items()}

        def _get_token(self) -> str:
            cookie_hdr = self.headers.get('Cookie', '')
            c = SimpleCookie()
            c.load(cookie_hdr)
            m = c.get('session')
            return m.value if m else ''

        def _current_user(self) -> dict | None:
            if not USE_DB:
                return {'id': 0, 'username': 'local', 'is_admin': True}
            return db.get_session_user(self._get_token())

        def _require_auth(self) -> dict | None:
            u = self._current_user()
            if not u:
                self._send_json({'error': 'Требуется авторизация'}, 401)
            return u

        def _require_admin(self) -> dict | None:
            u = self._current_user()
            if not u or not u.get('is_admin'):
                self._send_json({'error': 'Доступ запрещён'}, 403)
                return None
            return u

        def _serve_static(self, path: str):
            web = _web_dir()
            clean = path.lstrip('/')
            if not clean:
                clean = 'index.html'
            fpath = web / clean
            if not fpath.exists() or not fpath.is_file():
                # SPA fallback
                fpath = web / 'index.html'
            if not fpath.exists():
                self.send_response(404); self.end_headers(); return
            ext = fpath.suffix.lower()
            data = fpath.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', MIME.get(ext, 'application/octet-stream'))
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_html(self, name: str, **ctx):
            """Serve an HTML page from web/<name>.html with simple {{key}} substitution."""
            fpath = _web_dir() / name
            if not fpath.exists():
                self.send_response(404); self.end_headers(); return
            tmpl = fpath.read_text(encoding='utf-8')
            for k, v in ctx.items():
                tmpl = tmpl.replace('{{' + k + '}}', str(v))
            body = tmpl.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # ── routing ────────────────────────────────────────────────────────

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            p = parsed.path.rstrip('/')

            # Auth pages (HTML forms)
            if p == '/login':
                self._serve_html('login.html', error='')
                return
            if p == '/register':
                if USE_DB and db.get_setting('registration_open', 'true') == 'false':
                    self._serve_html('login.html', error='Регистрация отключена администратором.')
                    return
                self._serve_html('register.html', error='')
                return
            if p == '/logout':
                token = self._get_token()
                if USE_DB and token:
                    db.delete_session(token)
                self.send_response(302)
                self.send_header('Set-Cookie', 'session=; Path=/; Max-Age=0')
                self.send_header('Location', '/login')
                self.end_headers()
                return

            # Protected pages
            if p in ('', '/settings', '/admin'):
                if USE_DB and not self._current_user():
                    self._send_redirect('/login'); return

            # Settings page
            if p == '/settings':
                u = self._current_user()
                self._serve_html('settings.html', username=u['username'] if u else '',
                                 error='', success='')
                return

            # Admin page
            if p == '/admin':
                u = self._require_admin()
                if not u: return
                reg_open = db.get_setting('registration_open', 'true')
                self._serve_html('admin.html',
                                 username=u['username'],
                                 reg_open='checked' if reg_open == 'true' else '',
                                 error='', success='')
                return

            # ── API ────────────────────────────────────────────────────────
            catalog = get_catalog()

            if p == '/api/status':
                u = self._current_user()
                self._send_json({
                    'ok': True,
                    'user': {'id': u['id'], 'username': u['username'],
                             'is_admin': u['is_admin']} if u else None,
                    'artifacts': len(catalog.artifacts) if catalog else 0,
                    'containers': len(catalog.containers) if catalog else 0,
                    'armors': len(catalog.armors) if catalog else 0,
                    'last_update': last_update_ts(),
                })
                return

            if p == '/api/catalog':
                if not catalog:
                    self._send_error('Каталог ещё загружается', 503); return
                self._send_json(catalog.to_dict())
                return

            if p == '/api/presets':
                if not catalog:
                    self._send_json([]); return
                self._send_json(get_presets(catalog.stat_defs))
                return

            if p == '/api/inventory':
                u = self._require_auth()
                if not u: return
                if USE_DB:
                    self._send_json(db.get_inventory(u['id']))
                else:
                    from . import inventory as inv_store
                    self._send_json(inv_store.load())
                return

            if p == '/api/builds':
                u = self._require_auth()
                if not u: return
                if USE_DB:
                    self._send_json(db.get_builds(u['id']))
                else:
                    self._send_json([])
                return

            if p == '/api/users':
                u = self._require_admin()
                if not u: return
                if USE_DB:
                    self._send_json(db.list_users())
                else:
                    self._send_json([])
                return

            # Static files
            self._serve_static(parsed.path)

        def do_POST(self):
            parsed = urlparse(self.path)
            p = parsed.path.rstrip('/')
            ct = self.headers.get('Content-Type', '')

            # ── Auth forms ─────────────────────────────────────────────────
            if p == '/login':
                form = self._read_form()
                username = form.get('username', '').strip()
                password = form.get('password', '')
                if USE_DB:
                    user = db.get_user_by_name(username)
                    if user and db.verify_password(password, user['password_hash']):
                        token = db.create_session(user['id'])
                        self.send_response(302)
                        self.send_header('Set-Cookie', f'session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={db.SESSION_TTL_HOURS*3600}')
                        self.send_header('Location', '/')
                        self.end_headers()
                    else:
                        self._serve_html('login.html', error='Неверный логин или пароль')
                else:
                    self._send_redirect('/')
                return

            if p == '/register':
                if USE_DB and db.get_setting('registration_open', 'true') == 'false':
                    self._serve_html('register.html', error='Регистрация отключена')
                    return
                form = self._read_form()
                username = form.get('username', '').strip()
                password = form.get('password', '')
                if len(username) < 3:
                    self._serve_html('register.html', error='Имя пользователя: минимум 3 символа')
                    return
                if len(password) < 6:
                    self._serve_html('register.html', error='Пароль: минимум 6 символов')
                    return
                if USE_DB:
                    if db.get_user_by_name(username):
                        self._serve_html('register.html', error='Пользователь уже существует')
                        return
                    user = db.create_user(username, password)
                    token = db.create_session(user['id'])
                    self.send_response(302)
                    self.send_header('Set-Cookie', f'session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={db.SESSION_TTL_HOURS*3600}')
                    self.send_header('Location', '/')
                    self.end_headers()
                else:
                    self._send_redirect('/')
                return

            if p == '/settings/password':
                u = self._require_auth()
                if not u: return
                if 'application/json' in ct:
                    body = self._read_body()
                else:
                    body = self._read_form()
                old_pw = body.get('old_password', '')
                new_pw = body.get('new_password', '')
                if USE_DB:
                    full = db.get_user_by_name(u['username'])
                    if not db.verify_password(old_pw, full['password_hash']):
                        if 'application/json' in ct:
                            self._send_error('Неверный текущий пароль')
                        else:
                            self._serve_html('settings.html', username=u['username'],
                                             error='Неверный текущий пароль', success='')
                        return
                    if len(new_pw) < 6:
                        if 'application/json' in ct:
                            self._send_error('Пароль: минимум 6 символов')
                        else:
                            self._serve_html('settings.html', username=u['username'],
                                             error='Пароль: минимум 6 символов', success='')
                        return
                    db.change_password(u['id'], new_pw)
                if 'application/json' in ct:
                    self._send_json({'ok': True})
                else:
                    self._serve_html('settings.html', username=u['username'],
                                     error='', success='Пароль успешно изменён')
                return

            # ── Admin API ──────────────────────────────────────────────────
            if p == '/admin/toggle-registration':
                u = self._require_admin()
                if not u: return
                body = self._read_form() if 'form' in ct else self._read_body()
                val  = body.get('value', 'false')
                if USE_DB:
                    db.set_setting('registration_open', val)
                if 'application/json' in ct:
                    self._send_json({'ok': True, 'registration_open': val})
                else:
                    reg_open = db.get_setting('registration_open', 'true')
                    self._serve_html('admin.html', username=u['username'],
                                     reg_open='checked' if reg_open == 'true' else '',
                                     error='', success='Настройки сохранены')
                return

            if p == '/admin/delete-user':
                u = self._require_admin()
                if not u: return
                body = self._read_body()
                uid = int(body.get('user_id', 0))
                if USE_DB and uid:
                    db.delete_user(uid)
                self._send_json({'ok': True})
                return

            if p == '/api/catalog/refresh':
                u = self._require_admin()
                if not u: return
                ok = force_update()
                catalog = get_catalog()
                self._send_json({
                    'ok': ok,
                    'artifacts': len(catalog.artifacts) if catalog else 0,
                    'containers': len(catalog.containers) if catalog else 0,
                    'armors': len(catalog.armors) if catalog else 0,
                    'last_update': last_update_ts(),
                })
                return

            # ── User API ───────────────────────────────────────────────────
            catalog = get_catalog()

            if p == '/api/inventory':
                u = self._require_auth()
                if not u: return
                body = self._read_body()
                if USE_DB:
                    db.save_inventory(u['id'], body)
                else:
                    from . import inventory as inv_store
                    inv_store.save(body)
                self._send_json({'ok': True})
                return

            if p == '/api/builds':
                u = self._require_auth()
                if not u: return
                body = self._read_body()
                if USE_DB:
                    bid = db.save_build(u['id'], body.get('name', 'Сборка'), body.get('data', {}))
                    self._send_json({'ok': True, 'id': bid})
                else:
                    self._send_json({'ok': True})
                return

            if p == '/api/calc':
                u = self._require_auth()
                if not u: return
                if not catalog:
                    self._send_error('Каталог загружается', 503); return
                try:
                    body = self._read_body()
                    art_by_id  = {a.id: a for a in catalog.artifacts}
                    cont_by_id = {c.id: c for c in catalog.containers}
                    arm_by_id  = {a.id: a for a in catalog.armors}
                    armor     = arm_by_id.get(body.get('armor_id'))     if body.get('armor_id')     else None
                    container = cont_by_id.get(body.get('container_id')) if body.get('container_id') else None
                    artifacts = [art_by_id[i] for i in body.get('artifact_ids', []) if i in art_by_id]
                    result = calculate_build(armor, container, artifacts, catalog.stat_defs,
                                             body.get('mode', 'avg'), float(body.get('max_hp', 100)))
                    self._send_json(result)
                except Exception as e:
                    self._send_error(str(e))
                return

            if p == '/api/optimize':
                u = self._require_auth()
                if not u: return
                if not catalog:
                    self._send_error('Каталог загружается', 503); return
                try:
                    body = self._read_body()
                    results = optimize(
                        catalog=catalog,
                        inv_artifact_ids=body.get('inventory', {}).get('artifact_ids', []),
                        inv_container_ids=body.get('inventory', {}).get('container_ids', []),
                        inv_armor_ids=body.get('inventory', {}).get('armor_ids', []),
                        goal_weights=body.get('weights', {}),
                        mode=body.get('mode', 'avg'),
                        max_hp=float(body.get('max_hp', 100)),
                        top_n=int(body.get('top_n', 5)),
                    )
                    self._send_json(results)
                except Exception as e:
                    self._send_error(str(e))
                return

            if p.startswith('/api/builds/') and p.endswith('/delete'):
                u = self._require_auth()
                if not u: return
                try:
                    bid = int(p.split('/')[-2])
                    if USE_DB:
                        db.delete_build(bid, u['id'])
                    self._send_json({'ok': True})
                except Exception as e:
                    self._send_error(str(e))
                return

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


def run(host: str = '127.0.0.1', port: int = 0) -> int:
    if port == 0:
        port = find_free_port(8080)
    handler = make_handler()
    server = ThreadingHTTPServer((host, port), handler)
    print(f'Сервер: http://{host}:{port}')
    server.serve_forever()
    return port
