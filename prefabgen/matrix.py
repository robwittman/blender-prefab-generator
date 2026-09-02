"""Cartesian expansion of a matrix definition into named combinations.

Runs outside Blender - no bpy import, fully unit-testable.
"""
from __future__ import annotations

import itertools
from typing import Any, Iterator


def fmt(value: Any) -> str:
    """Format an axis value for use in a prefab name: 4.0 -> '4', 2.50 -> '2.5'."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(round(value, 4)).rstrip("0").rstrip(".")
    return str(value)


def expand(axes: dict[str, list], exclude: list[dict] | None = None) -> list[dict]:
    """Cartesian product of ``axes``, in declared order, minus ``exclude`` matches.

    An exclude entry is a partial combination; a combo is dropped when every key in
    the entry matches. A list value in an entry means "any of these".
    """
    if not axes:
        return []
    names = list(axes)
    combos = [dict(zip(names, values)) for values in itertools.product(*(axes[n] for n in names))]
    if not exclude:
        return combos
    return [c for c in combos if not any(_matches(c, e) for e in exclude)]


def _matches(combo: dict, rule: dict) -> bool:
    for key, wanted in rule.items():
        if key not in combo:
            return False
        actual = combo[key]
        if isinstance(wanted, list):
            if not any(_eq(actual, w) for w in wanted):
                return False
        elif not _eq(actual, wanted):
            return False
    return True


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


def render_name(template: str, combo: dict) -> str:
    """Fill ``template`` with formatted axis values, e.g. 'wall_{width}x{height}'."""
    return template.format(**{k: fmt(v) for k, v in combo.items()})
