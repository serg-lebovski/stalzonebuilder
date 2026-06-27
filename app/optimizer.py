from __future__ import annotations
from typing import Optional
from .models import Catalog, Artifact, Container, Armor
from .calc import calculate_build, _vitality_keys

ACCUMULATION_KEYS = {
    'radiation_accumulation', 'biological_accumulation', 'thermal_accumulation',
    'reaction_to_electroshock', 'electra_accumulation', 'psy_accumulation',
    'psycho_accumulation',
}

PRESETS: dict[str, dict] = {
    'speed': {
        'name': 'Скорость',
        'description': 'Максимальная скорость передвижения и выносливость',
        'weights': {
            'speed_modifier':             3.0,
            'sprint_speed_modifier':      2.5,
            'stamina_bonus':              1.5,
            'stamina_regeneration_bonus': 1.0,
            'max_weight_bonus':           0.3,
            **{k: -3.0 for k in ACCUMULATION_KEYS},
        },
    },
    'bullet': {
        'name': 'Пулестойкость',
        'description': 'Максимальная защита от урона',
        'weights': {
            'bullet_dmg_factor':          5.0,
            'tear_dmg_factor':            2.0,
            'explosion_dmg_factor':       1.5,
            'electra_dmg_factor':         1.0,
            'burn_dmg_factor':            1.0,
            'chemical_burn_dmg_factor':   1.0,
            'biological_protection':      1.0,
            'radiation_protection':       1.0,
            'thermal_protection':         1.0,
            'psycho_protection':          0.8,
            'bleeding_protection':        0.5,
            **{k: -2.5 for k in ACCUMULATION_KEYS},
        },
    },
    'effective_hp': {
        'name': 'Приведёнка',
        'description': 'Максимальное приведённое HP (Пулестойкость × Живучесть)',
        'weights': {
            'bullet_dmg_factor':    4.0,
            'tear_dmg_factor':      0.5,
            'explosion_dmg_factor': 0.5,
            **{k: -2.0 for k in ACCUMULATION_KEYS},
        },
        'add_vitality': True,
    },
    'balanced': {
        'name': 'Баланс',
        'description': 'Скорость + защиты без перекоса',
        'weights': {
            'speed_modifier':        2.0,
            'sprint_speed_modifier': 1.5,
            'stamina_bonus':         1.0,
            'bullet_dmg_factor':     2.0,
            'tear_dmg_factor':       1.0,
            'explosion_dmg_factor':  1.0,
            'bleeding_protection':   0.5,
            **{k: -2.0 for k in ACCUMULATION_KEYS},
        },
    },
}


def _art_score(art: Artifact, weights: dict, efficiency: float, mode: str) -> float:
    props = art.avg_props() if mode == 'avg' else art.max_props()
    return sum(weights.get(k, 0.0) * v * efficiency for k, v in props.items())


def optimize(
    catalog: Catalog,
    inv_artifact_ids: list[str],
    inv_container_ids: list[str],
    inv_armor_ids: list[str],
    goal_weights: dict,
    mode: str = 'avg',
    max_hp: float = 100.0,
    top_n: int = 5,
) -> list[dict]:
    """
    Find the best (armor, container, artifacts) combos from the player's inventory.

    Algorithm:
      For each (armor, container) pair:
        1. Score every available artifact under this container's efficiency.
        2. Greedily pick top `container.slots` artifacts.
        3. Compute build score as weighted sum of all total stats.
      Return top_n builds by score.

    This yields the global optimum for any linear objective.
    """
    art_by_id   = {a.id: a for a in catalog.artifacts}
    cont_by_id  = {c.id: c for c in catalog.containers}
    armor_by_id = {a.id: a for a in catalog.armors}

    inv_arts      = [art_by_id[i]   for i in inv_artifact_ids  if i in art_by_id]
    inv_conts     = [cont_by_id[i]  for i in inv_container_ids if i in cont_by_id]
    inv_armors    = [armor_by_id[i] for i in inv_armor_ids      if i in armor_by_id]

    if not inv_conts:
        return []

    # Enrich vitality weight for effective_hp preset (done by caller or here)
    weights = dict(goal_weights)
    vit_keys = _vitality_keys(catalog.stat_defs)
    for k in vit_keys:
        weights[k] = weights.get(k, 0.0) + 4.0

    results = []
    armor_pool: list[Optional[Armor]] = [None] + inv_armors

    for armor in armor_pool:
        for container in inv_conts:
            scored = sorted(
                inv_arts,
                key=lambda a: -_art_score(a, weights, container.efficiency, mode)
            )
            selected = scored[:container.slots]

            build = calculate_build(armor, container, selected, catalog.stat_defs, mode, max_hp)
            score = sum(weights.get(k, 0.0) * v for k, v in build['stats'].items())

            results.append({
                'score': round(score, 3),
                'armor': armor.to_dict() if armor else None,
                'container': container.to_dict(),
                'artifacts': [a.to_dict() for a in selected],
                'totals': build,
            })

    results.sort(key=lambda x: -x['score'])
    return results[:top_n]


def get_presets(stat_defs: dict) -> list[dict]:
    """Return presets enriched with vitality keys where needed."""
    out = []
    vit_keys = _vitality_keys(stat_defs)
    for pid, p in PRESETS.items():
        weights = dict(p['weights'])
        if p.get('add_vitality'):
            for k in vit_keys:
                weights[k] = weights.get(k, 0.0) + 4.0
        out.append({
            'id': pid,
            'name': p['name'],
            'description': p['description'],
            'weights': weights,
        })
    return out
