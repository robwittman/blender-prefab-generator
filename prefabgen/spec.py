"""Resolved prefab specs. Pure data - importable inside and outside Blender."""
from __future__ import annotations

import math

from dataclasses import dataclass, field
from typing import Any

MAP_ROLES = ("albedo", "normal", "roughness", "metallic", "ao", "height")


@dataclass(frozen=True)
class ReliefSpec:
    """Real geometric relief displaced from the height map.

    Displacement is masked to zero at every surface a neighbouring module touches, so
    mating planes stay exactly planar - see prefabgen/blender/relief.py.
    """

    strength: float = 0.03       # metres of displacement at full white
    resolution: float = 0.05     # metres per grid cell - how finely the height map is sampled
    feather: float = 0.06        # metres over which relief ramps back to flat at the edges
    mid_level: float = 0.5       # height value treated as "no displacement"

    def to_dict(self) -> dict:
        return {"strength": self.strength, "resolution": self.resolution,
                "feather": self.feather, "mid_level": self.mid_level}

    @classmethod
    def from_dict(cls, d: dict) -> "ReliefSpec":
        return cls(strength=float(d.get("strength", 0.03)),
                   resolution=float(d.get("resolution", 0.05)),
                   feather=float(d.get("feather", 0.06)),
                   mid_level=float(d.get("mid_level", 0.5)))


@dataclass(frozen=True)
class MaterialSpec:
    """A texture set. ``maps`` holds absolute paths keyed by role; any role may be
    missing, in which case the builder falls back to the scalar defaults below."""

    name: str
    display_name: str = ""
    tile_size: float = 1.0          # metres covered by one texture repeat
    maps: dict = field(default_factory=dict)
    base_color: tuple = (0.8, 0.8, 0.8, 1.0)
    roughness: float = 0.8
    metallic: float = 0.0
    normal_strength: float = 1.0
    normal_flip_green: bool = False  # True for DirectX-convention normal maps
    relief: Any = None               # ReliefSpec, or None for a flat surface
    search_dir: str = ""             # where auto-discovery looked, for error messages

    def to_dict(self) -> dict:
        return {"name": self.name, "display_name": self.display_name,
                "tile_size": self.tile_size, "maps": dict(self.maps),
                "base_color": list(self.base_color), "roughness": self.roughness,
                "metallic": self.metallic, "normal_strength": self.normal_strength,
                "normal_flip_green": self.normal_flip_green, "search_dir": self.search_dir,
                "relief": self.relief.to_dict() if self.relief else None}

    @classmethod
    def from_dict(cls, d: dict) -> "MaterialSpec":
        return cls(name=d["name"], display_name=d.get("display_name", ""),
                   tile_size=float(d.get("tile_size", 1.0)), maps=dict(d.get("maps", {})),
                   base_color=tuple(d.get("base_color", (0.8, 0.8, 0.8, 1.0))),
                   roughness=float(d.get("roughness", 0.8)),
                   metallic=float(d.get("metallic", 0.0)),
                   normal_strength=float(d.get("normal_strength", 1.0)),
                   normal_flip_green=bool(d.get("normal_flip_green", False)),
                   search_dir=d.get("search_dir", ""),
                   relief=ReliefSpec.from_dict(d["relief"]) if d.get("relief") else None)

    def missing_maps(self) -> list:
        import os
        return sorted(r for r, p in self.maps.items() if not os.path.exists(p))


@dataclass(frozen=True)
class Opening:
    """A rectangular hole cut through the full thickness of a wall."""

    kind: str
    width: float
    height: float
    sill: float = 0.0      # bottom of the opening, above the wall base
    offset: float = 0.0    # horizontal centre offset from the wall centre

    def bounds(self, wall_width: float) -> tuple:
        """(x0, x1, z0, z1) in wall-local space, before the origin shift."""
        cx = wall_width / 2.0 + self.offset
        return (cx - self.width / 2.0, cx + self.width / 2.0,
                self.sill, self.sill + self.height)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "width": self.width, "height": self.height,
                "sill": self.sill, "offset": self.offset}

    @classmethod
    def from_dict(cls, d: dict) -> "Opening":
        return cls(kind=d.get("kind", "opening"), width=float(d["width"]),
                   height=float(d["height"]), sill=float(d.get("sill", 0.0)),
                   offset=float(d.get("offset", 0.0)))


@dataclass(frozen=True)
class WallSpec:
    """One cell of the matrix, fully resolved. This is what the builder consumes."""

    id: str
    name: str                          # filename stem / object name
    display_name: str                  # what a creator sees in the picker
    width: float
    height: float
    thickness: float
    material: MaterialSpec
    openings: tuple = ()
    reveal_material: Any = None        # MaterialSpec or None (None = reuse `material`)
    origin: str = "bottom_center"      # bottom_center | center | min_corner
    category: str = "Walls"
    tags: tuple = ()
    source: str = "procedural"
    type: str = "wall"

    def dimensions(self) -> dict:
        return {"width": self.width, "height": self.height,
                "thickness": self.thickness, "unit": "m"}

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "source": self.source,
            "name": self.name, "display_name": self.display_name,
            "width": self.width, "height": self.height, "thickness": self.thickness,
            "material": self.material.to_dict(),
            "reveal_material": self.reveal_material.to_dict() if self.reveal_material else None,
            "openings": [o.to_dict() for o in self.openings],
            "origin": self.origin, "category": self.category, "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WallSpec":
        rev = d.get("reveal_material")
        return cls(
            id=d["id"], name=d["name"], display_name=d.get("display_name", d["name"]),
            width=float(d["width"]), height=float(d["height"]),
            thickness=float(d["thickness"]),
            material=MaterialSpec.from_dict(d["material"]),
            reveal_material=MaterialSpec.from_dict(rev) if rev else None,
            openings=tuple(Opening.from_dict(o) for o in d.get("openings", [])),
            origin=d.get("origin", "bottom_center"),
            category=d.get("category", "Walls"), tags=tuple(d.get("tags", [])),
            source=d.get("source", "procedural"), type=d.get("type", "wall"),
        )


@dataclass(frozen=True)
class RoofSpec:
    """One roof piece. Footprints tile the same plan grid the walls use: ``span`` runs
    along the eave and ``run`` is horizontal depth up the slope, so the sloped panel is
    longer than its run by 1/cos(angle) while still landing on the grid."""

    id: str
    name: str
    display_name: str
    piece: str                    # slab | ridge | hip | valley | hip_cap | valley_cap
    angle: float                  # pitch in degrees
    pitch: str                    # the pitch's config name, for display
    material: MaterialSpec
    span: float = 0.0
    run: float = 0.0
    thickness: float = 0.18       # perpendicular to the slope
    cap_width: float = 0.30       # horizontal width of ridge/hip/valley trim
    cap_thickness: float = 0.06
    origin: str = "footprint_center"
    category: str = "Roofs"
    tags: tuple = ()
    source: str = "procedural"
    type: str = "roof"

    @property
    def rise(self) -> float:
        return self.run * math.tan(math.radians(self.angle))

    @property
    def slope_length(self) -> float:
        return self.run / math.cos(math.radians(self.angle))

    @property
    def vertical_thickness(self) -> float:
        """Thickness measured vertically - the ends are plumb cuts, so slabs butt."""
        return self.thickness / math.cos(math.radians(self.angle))

    def dimensions(self) -> dict:
        return {"span": self.span, "run": self.run, "rise": round(self.rise, 6),
                "slope_length": round(self.slope_length, 6), "thickness": self.thickness,
                "pitch_degrees": self.angle, "unit": "m"}

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "source": self.source,
                "name": self.name, "display_name": self.display_name, "piece": self.piece,
                "angle": self.angle, "pitch": self.pitch, "span": self.span, "run": self.run,
                "thickness": self.thickness, "cap_width": self.cap_width,
                "cap_thickness": self.cap_thickness, "material": self.material.to_dict(),
                "origin": self.origin, "category": self.category, "tags": list(self.tags)}

    @classmethod
    def from_dict(cls, d: dict) -> "RoofSpec":
        return cls(id=d["id"], name=d["name"], display_name=d.get("display_name", d["name"]),
                   piece=d["piece"], angle=float(d["angle"]), pitch=d.get("pitch", ""),
                   material=MaterialSpec.from_dict(d["material"]),
                   span=float(d.get("span", 0.0)), run=float(d.get("run", 0.0)),
                   thickness=float(d.get("thickness", 0.18)),
                   cap_width=float(d.get("cap_width", 0.30)),
                   cap_thickness=float(d.get("cap_thickness", 0.06)),
                   origin=d.get("origin", "footprint_center"),
                   category=d.get("category", "Roofs"), tags=tuple(d.get("tags", [])),
                   source=d.get("source", "procedural"), type=d.get("type", "roof"))


SPEC_TYPES = {"wall": WallSpec, "roof": RoofSpec}


def spec_from_dict(d: dict):
    """Rebuild whichever spec type this dict describes."""
    kind = d.get("type", "wall")
    try:
        return SPEC_TYPES[kind].from_dict(d)
    except KeyError:
        raise ValueError(f"no spec type for {kind!r}; known: {sorted(SPEC_TYPES)}")


def validate(spec, min_border: float = 0.1):
    if isinstance(spec, RoofSpec):
        return _validate_roof(spec)
    return _validate_wall(spec, min_border)


def _validate_roof(spec: RoofSpec):
    if not 0.0 < spec.angle < 90.0:
        return f"pitch {spec.angle} must be between 0 and 90 degrees"
    if spec.thickness <= 0:
        return "non-positive thickness"
    needs_span = spec.piece in ("slab", "ridge")
    needs_run = spec.piece in ("slab", "hip", "valley", "hip_cap", "valley_cap")
    if needs_span and spec.span <= 0:
        return f"{spec.piece} needs a positive span"
    if needs_run and spec.run <= 0:
        return f"{spec.piece} needs a positive run"
    return None


def _validate_wall(spec: WallSpec, min_border: float = 0.1):
    """Return a human-readable reason this spec is unbuildable, or None."""
    if spec.width <= 0 or spec.height <= 0 or spec.thickness <= 0:
        return "non-positive dimension"
    for o in spec.openings:
        x0, x1, z0, z1 = o.bounds(spec.width)
        if x0 < min_border or x1 > spec.width - min_border:
            return f"{o.kind} ({o.width}m wide) needs {min_border}m of border in a {spec.width}m wall"
        if z0 < -1e-9 or z1 > spec.height - min_border:
            return f"{o.kind} ({o.height}m tall, sill {o.sill}m) does not fit a {spec.height}m wall"
    for a, b in _pairs(spec.openings):
        ax0, ax1, az0, az1 = a.bounds(spec.width)
        bx0, bx1, bz0, bz1 = b.bounds(spec.width)
        if ax0 < bx1 and bx0 < ax1 and az0 < bz1 and bz0 < az1:
            return f"openings {a.kind} and {b.kind} overlap"
    return None


def _pairs(items):
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            yield items[i], items[j]
