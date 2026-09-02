"""sRGB hex -> linear RGBA, which is what Blender's shader inputs expect."""
from __future__ import annotations


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def parse(value, default=(0.8, 0.8, 0.8, 1.0)) -> tuple:
    """Accept '#rrggbb', [r,g,b], [r,g,b,a] (0-1 linear) or None."""
    if value is None:
        return default
    if isinstance(value, str):
        s = value.lstrip("#")
        if len(s) != 6:
            raise ValueError(f"expected #rrggbb, got {value!r}")
        rgb = [int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        return tuple(_srgb_to_linear(c) for c in rgb) + (1.0,)
    vals = [float(v) for v in value]
    if len(vals) == 3:
        vals.append(1.0)
    return tuple(vals)
