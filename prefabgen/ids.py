"""Stable prefab identifiers.

A prefab's ID must survive regeneration, renaming and changes to the display-name
template, because creator-authored levels reference it. So it is derived from the
*semantic* axis values, not from the filename, and numeric axes are normalised to
integer millimetres so 2.5 and 2.50 can never drift apart.
"""
from __future__ import annotations

from .matrix import fmt

# No default template: an id is built from whatever axes the part actually declares,
# so a new part type (floors, corners) gets stable ids without configuring anything.
# Set `id_template` on a part for a prettier shape - see config/walls.yaml.
DEFAULT_ID_TEMPLATE = None


def id_fields(part_type: str, combo: dict) -> dict:
    """Axis values plus an integer-millimetre form of every numeric axis."""
    fields: dict = {"type": part_type}
    for key, value in combo.items():
        fields[key] = fmt(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            fields[f"{key}_mm"] = int(round(float(value) * 1000))
    return fields


def make_id(part_type: str, combo: dict, template=DEFAULT_ID_TEMPLATE) -> str:
    if not template:
        return ".".join([part_type] + [_token(v) for v in combo.values()])
    try:
        return template.format(**id_fields(part_type, combo))
    except KeyError as exc:
        raise ValueError(f"id_template references unknown axis {exc}") from exc


def _token(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(round(float(value) * 1000)))
    return fmt(value)
