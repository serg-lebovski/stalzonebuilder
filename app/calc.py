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


ARTIFACT_LEVELS   = [0, 5, 10, 15]
ARTIFACT_QUALITIES = [100, 115, 130, 145, 160, 175]
ARMOR_QUALITIES    = [100, 115, 130, 145, 160, 175]


def _art_props(art: Artifact, level: int | None, quality: int | None) -> dict:
    """
    Compute artifact props using level interpolation + quality multiplier.
    level   : 0 / 5 / 10 / 15  (maps linearly to min..max range)
    quality : 100 / 115 / 130 / 145 / 160 / 175  (percentage applied on top)
    Defaults: level=15 (max stats), quality=100 (no extra bonus).
    """
    t = (level if level is not None else 15) / 15.0
    q = (quality if quality is not None else 100) / 100.0
    return {k: (mn + (mx - mn) * t) * q for k, (mn, mx) in art.props.items()}


def calculate_build(
    armor: Optional[Armor],
    container: Optional[Container],
    artifacts: list[Artifact],
    stat_defs: dict,
    mode: str = 'avg',
    max_hp: float = 100.0,
    artifact_levels: list[int] | None = None,
    artifact_qualities: list[int] | None = None,
    armor_quality: int | None = None,
) -> dict:
    """
    Compute total stats and effective HP for a given build.

    artifact_levels   : per-artifact list of 0/5/10/15  (default 15)
    artifact_qualities: per-artifact list of 100..175    (default 100)
    armor_quality     : quality multiplier for armor (100..175, default 100)
    mode              : legacy fallback for optimizer ('avg'/'max')
    """
    totals: dict[str, float] = {}

    if armor:
        arm_q = (armor_quality if armor_quality is not None else 100) / 100.0
        for k, v in armor.stats.items():
            totals[k] = totals.get(k, 0.0) + v * arm_q

    eff = container.efficiency if container else 1.0
    slots = container.slots if container else 0

    chosen = artifacts[:slots]
    for i, art in enumerate(chosen):
        level   = artifact_levels[i]   if artifact_levels   and i < len(artifact_levels)   else None
        quality = artifact_qualities[i] if artifact_qualities and i < len(artifact_qualities) else None
        props   = _art_props(art, level, quality)
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
