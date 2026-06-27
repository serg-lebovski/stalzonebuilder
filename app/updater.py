"""
Автообновление каталога из EXBO-Studio/stalzone-database.
Запускается в фоновом потоке при старте и раз в сутки.
"""
from __future__ import annotations
import threading
import time
import logging

log = logging.getLogger('updater')
UPDATE_INTERVAL = 24 * 3600  # раз в 24 часа

_catalog_lock = threading.Lock()
_catalog_ref: list = [None]   # список из одного элемента для мутабельного хранения
_last_update: list = [0.0]
_update_listeners: list = []


def get_catalog():
    with _catalog_lock:
        return _catalog_ref[0]


def on_catalog_update(cb):
    """Register a callback called with new Catalog after each update."""
    _update_listeners.append(cb)


def _do_update(force: bool = False):
    from .data_loader import load_catalog
    now = time.time()
    if not force and (now - _last_update[0]) < UPDATE_INTERVAL:
        return False
    try:
        log.info('Обновление каталога...')
        new_catalog = load_catalog()
        with _catalog_lock:
            _catalog_ref[0] = new_catalog
            _last_update[0] = now
        for cb in _update_listeners:
            try:
                cb(new_catalog)
            except Exception as e:
                log.warning(f'Ошибка в callback обновления: {e}')
        log.info('Каталог обновлён.')
        return True
    except Exception as e:
        log.error(f'Ошибка обновления каталога: {e}')
        return False


def _loop():
    _do_update(force=True)          # первый раз при старте
    while True:
        time.sleep(3600)            # проверяем раз в час
        _do_update(force=False)     # обновляем если прошли сутки


def start_background_updater():
    """Start background catalog refresh thread."""
    t = threading.Thread(target=_loop, daemon=True, name='catalog-updater')
    t.start()
    return t


def force_update() -> bool:
    """Manually trigger a reload (for admin panel)."""
    return _do_update(force=True)


def last_update_ts() -> float:
    return _last_update[0]
