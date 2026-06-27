"""
PostgreSQL-слой на чистом psycopg2.
Схема:
  users      — аккаунты (id, username, password_hash, is_admin, created_at)
  settings   — глобальные настройки (key, value)
  sessions   — токены сессий (token, user_id, expires_at)
  user_inventory — инвентарь игрока (user_id, artifact_ids[], container_ids[], armor_ids[])
  user_builds    — сохранённые сборки (id, user_id, name, data jsonb, created_at)
"""
from __future__ import annotations
import os
import json
import hashlib
import secrets
import time
from datetime import datetime, timedelta

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

DB_URL = os.environ.get('DB_URL', '')
SESSION_TTL_HOURS = 24 * 7   # 7 days
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = '12345678'

_conn = None


def _get_conn():
    global _conn
    if _conn is None or _conn.closed:
        if not HAS_PSYCOPG2:
            raise RuntimeError('psycopg2 не установлен. Выполните: pip install psycopg2-binary')
        if not DB_URL:
            raise RuntimeError('DB_URL не задан. Установите переменную окружения DB_URL.')
        _conn = psycopg2.connect(DB_URL, client_encoding='utf8')
        _conn.autocommit = True
    return _conn


def _cur():
    return _get_conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f'{salt}:{h}'


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(':', 1)
        return hashlib.sha256((salt + password).encode()).hexdigest() == h
    except Exception:
        return False


# ─── Schema ────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS user_inventory (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    artifact_ids  TEXT[] NOT NULL DEFAULT '{}',
    container_ids TEXT[] NOT NULL DEFAULT '{}',
    armor_ids     TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS user_builds (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL DEFAULT '',
    data       JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_builds_user   ON user_builds(user_id);
"""


def init_db():
    """Create tables and seed admin account + defaults."""
    with _cur() as cur:
        cur.execute(SCHEMA_SQL)

        # Default settings
        cur.execute("""
            INSERT INTO settings(key, value) VALUES ('registration_open', 'true')
            ON CONFLICT (key) DO NOTHING
        """)

        # Admin account
        cur.execute('SELECT id FROM users WHERE username = %s', (ADMIN_USERNAME,))
        if not cur.fetchone():
            ph = hash_password(ADMIN_PASSWORD)
            cur.execute(
                'INSERT INTO users(username, password_hash, is_admin) VALUES (%s, %s, TRUE)',
                (ADMIN_USERNAME, ph)
            )
            print(f'Создан администратор: {ADMIN_USERNAME} / {ADMIN_PASSWORD}')


# ─── Settings ──────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = '') -> str:
    try:
        with _cur() as cur:
            cur.execute('SELECT value FROM settings WHERE key = %s', (key,))
            row = cur.fetchone()
            return row['value'] if row else default
    except Exception:
        return default


def set_setting(key: str, value: str):
    with _cur() as cur:
        cur.execute("""
            INSERT INTO settings(key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (key, value))


# ─── Users ─────────────────────────────────────────────────────────────────

def get_user_by_id(user_id: int) -> dict | None:
    with _cur() as cur:
        cur.execute('SELECT id, username, is_admin, created_at FROM users WHERE id = %s', (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_user_by_name(username: str) -> dict | None:
    with _cur() as cur:
        cur.execute('SELECT * FROM users WHERE username = %s', (username,))
        row = cur.fetchone()
        return dict(row) if row else None


def create_user(username: str, password: str) -> dict:
    ph = hash_password(password)
    with _cur() as cur:
        cur.execute(
            'INSERT INTO users(username, password_hash) VALUES (%s, %s) RETURNING id, username, is_admin',
            (username, ph)
        )
        row = cur.fetchone()
        # create empty inventory
        cur.execute('INSERT INTO user_inventory(user_id) VALUES (%s) ON CONFLICT DO NOTHING', (row['id'],))
        return dict(row)


def change_password(user_id: int, new_password: str):
    ph = hash_password(new_password)
    with _cur() as cur:
        cur.execute('UPDATE users SET password_hash = %s WHERE id = %s', (ph, user_id))


def list_users() -> list[dict]:
    with _cur() as cur:
        cur.execute('SELECT id, username, is_admin, created_at FROM users ORDER BY id')
        return [dict(r) for r in cur.fetchall()]


def delete_user(user_id: int):
    with _cur() as cur:
        cur.execute('DELETE FROM users WHERE id = %s AND is_admin = FALSE', (user_id,))


# ─── Sessions ──────────────────────────────────────────────────────────────

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS)
    with _cur() as cur:
        cur.execute(
            'INSERT INTO sessions(token, user_id, expires_at) VALUES (%s, %s, %s)',
            (token, user_id, expires)
        )
    return token


def get_session_user(token: str) -> dict | None:
    if not token:
        return None
    with _cur() as cur:
        cur.execute("""
            SELECT u.id, u.username, u.is_admin
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token = %s AND s.expires_at > NOW()
        """, (token,))
        row = cur.fetchone()
        return dict(row) if row else None


def delete_session(token: str):
    with _cur() as cur:
        cur.execute('DELETE FROM sessions WHERE token = %s', (token,))


def cleanup_sessions():
    with _cur() as cur:
        cur.execute('DELETE FROM sessions WHERE expires_at < NOW()')


# ─── Inventory ─────────────────────────────────────────────────────────────

def get_inventory(user_id: int) -> dict:
    with _cur() as cur:
        cur.execute('SELECT artifact_ids, container_ids, armor_ids FROM user_inventory WHERE user_id = %s', (user_id,))
        row = cur.fetchone()
        if row:
            return {'artifact_ids': list(row['artifact_ids']),
                    'container_ids': list(row['container_ids']),
                    'armor_ids': list(row['armor_ids'])}
        return {'artifact_ids': [], 'container_ids': [], 'armor_ids': []}


def save_inventory(user_id: int, inv: dict):
    with _cur() as cur:
        cur.execute("""
            INSERT INTO user_inventory(user_id, artifact_ids, container_ids, armor_ids)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
              SET artifact_ids  = EXCLUDED.artifact_ids,
                  container_ids = EXCLUDED.container_ids,
                  armor_ids     = EXCLUDED.armor_ids
        """, (user_id,
              inv.get('artifact_ids', []),
              inv.get('container_ids', []),
              inv.get('armor_ids', [])))


# ─── Saved builds ──────────────────────────────────────────────────────────

def get_builds(user_id: int) -> list[dict]:
    with _cur() as cur:
        cur.execute('SELECT id, name, data, created_at FROM user_builds WHERE user_id = %s ORDER BY created_at DESC', (user_id,))
        return [{'id': r['id'], 'name': r['name'], 'data': r['data'],
                 'created_at': r['created_at'].isoformat()} for r in cur.fetchall()]


def save_build(user_id: int, name: str, data: dict) -> int:
    with _cur() as cur:
        cur.execute(
            'INSERT INTO user_builds(user_id, name, data) VALUES (%s, %s, %s) RETURNING id',
            (user_id, name, json.dumps(data, ensure_ascii=False))
        )
        return cur.fetchone()['id']


def delete_build(build_id: int, user_id: int):
    with _cur() as cur:
        cur.execute('DELETE FROM user_builds WHERE id = %s AND user_id = %s', (build_id, user_id))
