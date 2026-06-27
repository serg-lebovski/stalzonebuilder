from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Tuple, List, Set


@dataclass
class StatDef:
    key: str
    name_ru: str
    unit: str       # '', '%', 'кг'
    direction: int  # +1 bonus, -1 accumulation/penalty
    sources: Set[str] = field(default_factory=set)  # 'artifact', 'armor'

    def to_dict(self):
        return {
            'key': self.key,
            'name_ru': self.name_ru,
            'unit': self.unit,
            'direction': self.direction,
            'sources': list(self.sources),
        }


@dataclass
class Artifact:
    id: str
    name: str
    category: str
    color: str
    props: Dict[str, Tuple[float, float]]  # {stat_key: (min, max)}
    icon_url: str = ''

    def avg_props(self) -> Dict[str, float]:
        return {k: (v[0] + v[1]) / 2 for k, v in self.props.items()}

    def max_props(self) -> Dict[str, float]:
        return {k: v[1] for k, v in self.props.items()}

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'color': self.color,
            'icon_url': self.icon_url,
            'props': {k: {'min': round(v[0], 4), 'max': round(v[1], 4)}
                      for k, v in self.props.items()},
        }


@dataclass
class Container:
    id: str
    name: str
    slots: int
    efficiency: float       # multiplier, e.g. 1.5 for 150%
    inner_protection: float # e.g. 95.0
    weight: float
    icon_url: str = ''

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slots': self.slots,
            'efficiency': round(self.efficiency, 4),
            'efficiency_pct': round(self.efficiency * 100, 1),
            'inner_protection': self.inner_protection,
            'weight': self.weight,
            'icon_url': self.icon_url,
        }


@dataclass
class Armor:
    id: str
    name: str
    category: str
    color: str
    stats: Dict[str, float]  # {stat_key: value}
    weight: float
    icon_url: str = ''
    rank: str = ''

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'color': self.color,
            'rank': self.rank,
            'icon_url': self.icon_url,
            'stats': {k: round(v, 4) for k, v in self.stats.items()},
            'weight': self.weight,
        }


@dataclass
class Catalog:
    artifacts: List[Artifact]
    containers: List[Container]
    armors: List[Armor]
    stat_defs: Dict[str, StatDef]

    def to_dict(self):
        return {
            'artifacts': [a.to_dict() for a in self.artifacts],
            'containers': [c.to_dict() for c in self.containers],
            'armors': [a.to_dict() for a in self.armors],
            'stat_defs': {k: v.to_dict() for k, v in self.stat_defs.items()},
        }
