from __future__ import annotations
import json
import urllib.request
import zipfile
import io
from .models import Artifact, Container, Armor, StatDef, Catalog

DB_ZIP_URL = 'https://github.com/EXBO-Studio/stalzone-database/archive/refs/heads/main.zip'
ZIP_PREFIX = 'stalzone-database-main/'

BONUS_COLOR = '53C353'

# Container-specific field keys
CONT_KEY_EFFICIENCY   = 'stalker.tooltip.backpack.stat_name.effectiveness'
CONT_KEY_SLOTS        = 'stalker.tooltip.backpack.info.size'
CONT_KEY_INNER_PROT   = 'stalker.tooltip.backpack.stat_name.inner_protection'
KEY_WEIGHT            = 'core.tooltip.info.weight'

ART_FACTOR_PREFIX     = 'artefact_properties.factor.'


def _unit(formatted_ru: str) -> str:
    if not formatted_ru:
        return ''
    s = formatted_ru.strip()
    if '%' in s:
        return '%'
    if 'кг' in s:
        return 'кг'
    return ''


def _direction(color: str) -> int:
    return 1 if color and color.upper() == BONUS_COLOR.upper() else -1


def _all_elements(infoBlocks: list) -> list:
    out = []
    for block in infoBlocks:
        out.extend(block.get('elements', []))
    return out


def _parse_artifact(data: dict, stat_defs: dict) -> Artifact | None:
    item_id = data.get('id', '')
    category = data.get('category', '')
    name = data.get('name', {}).get('lines', {}).get('ru', item_id)
    color = data.get('color', 'DEFAULT')

    props: dict[str, tuple[float, float]] = {}
    for elem in _all_elements(data.get('infoBlocks', [])):
        if elem.get('type') != 'range':
            continue
        name_obj = elem.get('name', {})
        full_key = name_obj.get('key', '')
        if ART_FACTOR_PREFIX not in full_key:
            continue
        stat_key = full_key.split('.')[-1]
        min_v = float(elem.get('min', 0) or 0)
        max_v = float(elem.get('max', 0) or 0)
        props[stat_key] = (min_v, max_v)

        if stat_key not in stat_defs:
            fmt = elem.get('formatted', {})
            stat_defs[stat_key] = StatDef(
                key=stat_key,
                name_ru=name_obj.get('lines', {}).get('ru', stat_key),
                unit=_unit(fmt.get('value', {}).get('ru', '')),
                direction=_direction(fmt.get('valueColor', '')),
                sources={'artifact'},
            )
        else:
            stat_defs[stat_key].sources.add('artifact')

    if not props:
        return None
    return Artifact(id=item_id, name=name, category=category, color=color, props=props)


def _parse_container(data: dict) -> Container | None:
    item_id = data.get('id', '')
    name = data.get('name', {}).get('lines', {}).get('ru', item_id)
    slots = 0
    efficiency = 1.0
    inner_protection = 100.0
    weight = 0.0

    for elem in _all_elements(data.get('infoBlocks', [])):
        if elem.get('type') != 'numeric':
            continue
        fk = elem.get('name', {}).get('key', '')
        val = float(elem.get('value') or 0)
        if fk == CONT_KEY_SLOTS:
            slots = int(val)
        elif fk == CONT_KEY_EFFICIENCY:
            efficiency = val / 100.0
        elif fk == CONT_KEY_INNER_PROT:
            inner_protection = val
        elif fk == KEY_WEIGHT:
            weight = val

    if slots == 0:
        return None
    return Container(id=item_id, name=name, slots=slots, efficiency=efficiency,
                     inner_protection=inner_protection, weight=weight)


def _parse_armor(data: dict, stat_defs: dict) -> Armor | None:
    item_id = data.get('id', '')
    category = data.get('category', '')
    name = data.get('name', {}).get('lines', {}).get('ru', item_id)
    color = data.get('color', 'DEFAULT')
    weight = 0.0
    stats: dict[str, float] = {}

    for elem in _all_elements(data.get('infoBlocks', [])):
        etype = elem.get('type')
        name_obj = elem.get('name', {})
        fk = name_obj.get('key', '')
        val = float(elem.get('value') or 0)

        if etype == 'numeric' and fk == KEY_WEIGHT:
            weight = val
            continue
        if etype == 'numeric' and ART_FACTOR_PREFIX in fk:
            stat_key = fk.split('.')[-1]
            stats[stat_key] = val
            if stat_key not in stat_defs:
                fmt = elem.get('formatted', {})
                stat_defs[stat_key] = StatDef(
                    key=stat_key,
                    name_ru=name_obj.get('lines', {}).get('ru', stat_key),
                    unit=_unit(fmt.get('value', {}).get('ru', '')),
                    direction=1,
                    sources={'armor'},
                )
            else:
                stat_defs[stat_key].sources.add('armor')

    if not stats:
        return None
    return Armor(id=item_id, name=name, category=category, color=color,
                 stats=stats, weight=weight)


def load_catalog(progress_cb=None) -> Catalog:
    def log(msg):
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg)

    log('Загрузка базы данных с GitHub...')
    try:
        req = urllib.request.Request(
            DB_ZIP_URL,
            headers={'User-Agent': 'StalZoneBuilder/1.0'}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            zip_data = resp.read()
    except Exception as e:
        raise ConnectionError(f'Не удалось загрузить базу данных: {e}')

    log(f'Архив загружен ({len(zip_data) // 1024} КБ), разбор...')
    zf = zipfile.ZipFile(io.BytesIO(zip_data))

    listing_path = ZIP_PREFIX + 'global/listing.json'
    with zf.open(listing_path) as f:
        listing = json.load(f)

    stat_defs: dict[str, StatDef] = {}
    artifacts: list[Artifact] = []
    containers: list[Container] = []
    armors: list[Armor] = []

    for entry in listing:
        rel_path = entry.get('data', '').lstrip('/')
        zip_path = ZIP_PREFIX + 'global/' + rel_path
        try:
            with zf.open(zip_path) as f:
                data = json.load(f)
        except (KeyError, json.JSONDecodeError, Exception):
            continue

        if rel_path.startswith('items/artefact/'):
            obj = _parse_artifact(data, stat_defs)
            if obj:
                artifacts.append(obj)
        elif rel_path.startswith('items/containers/'):
            obj = _parse_container(data)
            if obj:
                containers.append(obj)
        elif rel_path.startswith('items/armor/'):
            obj = _parse_armor(data, stat_defs)
            if obj:
                armors.append(obj)

    # Sort for consistent UI
    artifacts.sort(key=lambda a: (a.category, a.name))
    containers.sort(key=lambda c: (c.slots, c.name))
    armors.sort(key=lambda a: (a.category, a.name))

    log(f'Готово: {len(artifacts)} артефактов, {len(containers)} контейнеров, {len(armors)} костюмов')
    return Catalog(artifacts=artifacts, containers=containers, armors=armors, stat_defs=stat_defs)
