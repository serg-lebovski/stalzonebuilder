from __future__ import annotations
from typing import Optional
from .models import Artifact, Container, Armor, Catalog


def _vitality_keys(stat_defs: dict) -> list[str]:
    """Return stat keys whose Russian name contains 'живучесть'."""
    return [k for k, sd in stat_defs.items() if 'живучесть' in sd.name_ru.lower()]


def compute_effective_hp(
    total_stats: dict,
    stat_defs: dict,
    max_hp: float = 100.0,
) -> float:
    """
    Приведёнка = (Здоровье + Пулестойкость) × (1 + Живучесть)

    Живучесть хранится как десятичная дробь (0.15 = +15%).
    Пулестойкость — stat key 'bullet_dmg_factor' (от костюма + артефактов).
    Живучесть    — все статы, в названии которых есть 'живучесть'.
    """
    bullet = total_stats.get('bullet_dmg_factor', 0.0)
    vitality = sum(total_stats.get(k, 0.0) for k in _vitality_keys(stat_defs))
    return (max_hp + bullet) * (1.0 + vitality)


def calculate_build(
    armor: Optional[Armor],
    container: Optional[Container],
    artifacts: list[Artifact],
    stat_defs: dict,
    mode: str = 'avg',
    max_hp: float = 100.0,
) -> dict:
    """
    Compute total stats and effective HP for a given build.

    mode: 'avg' uses (min+max)/2, 'max' uses max value.
    Returns:
        {stats, effective_hp, meta}
    """
    totals: dict[str, float] = {}

    if armor:
        for k, v in armor.stats.items():
            totals[k] = totals.get(k, 0.0) + v

    eff = container.efficiency if container else 1.0
    slots = container.slots if container else 0

    chosen = artifacts[:slots]
    for art in chosen:
        props = art.max_props() if mode == 'max' else art.avg_props()
        for k, v in props.items():
            totals[k] = totals.get(k, 0.0) + v * eff

    eff_hp = compute_effective_hp(totals, stat_defs, max_hp)

    return {
        'stats': {k: round(v, 4) for k, v in totals.items()},
        'effective_hp': round(eff_hp, 2),
        'meta': {
            'slots_used': len(chosen),
            'slots_total': slots,
            'efficiency_pct': round(eff * 100, 1),
            'mode': mode,
            'max_hp_base': max_hp,
        },
    }
