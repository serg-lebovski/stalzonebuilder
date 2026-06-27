from __future__ import annotations
import json
import os
import pathlib

APP_NAME = 'StalZoneBuilder'

EMPTY_INVENTORY = {
    'artifact_ids': [],
    'container_ids': [],
    'armor_ids': [],
    'saved_builds': [],
}


def _data_dir() -> pathlib.Path:
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    d = pathlib.Path(appdata) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _inv_path() -> pathlib.Path:
    return _data_dir() / 'inventory.json'


def load() -> dict:
    path = _inv_path()
    if not path.exists():
        return dict(EMPTY_INVENTORY)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for key in EMPTY_INVENTORY:
            if key not in data:
                data[key] = EMPTY_INVENTORY[key]
        return data
    except Exception:
        return dict(EMPTY_INVENTORY)


def save(inventory: dict) -> None:
    path = _inv_path()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)
