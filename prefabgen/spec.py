"""Resolved prefab specs. Pure data - importable inside and outside Blender."""
from __future__ import annotations

import math

from dataclasses import dataclass, field
from typing import Any

MAP_ROLES = ("albedo", "normal", "roughness", "metallic", "ao", "height")
LEAF_STYLES = ("braced", "banded")            # ledged-and-braced, iron-banded
WINDOW_PATTERNS = ("single", "cross", "grid")


@dataclass(frozen=True)
class ReliefSpec:
    """Real geometric relief displaced from the height map.

    Displacement is masked to zero at every surface a neighbouring module touches, so
    mating planes stay exactly planar - see prefabgen/blender/relief.py.
    """

    strength: float = 0.03       # metres of displacement at full white
    resolution: float = 0.05     # metres per grid cell - how finely the height map is sampled
    mid_level: float = 0.5       # height value treated as "no displacement"

    def to_dict(self) -> dict:
        return {"strength": self.strength, "resolution": self.resolution,
                "mid_level": self.mid_level}

    @classmethod
    def from_dict(cls, d: dict) -> "ReliefSpec":
        return cls(strength=float(d.get("strength", 0.03)),
                   resolution=float(d.get("resolution", 0.05)),
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
    kind: str = "opaque"             # opaque | glass
    opacity: float = 1.0             # < 1 exports as glTF alphaMode BLEND
    normal_flip_green: bool = False  # True for DirectX-convention normal maps
    relief: Any = None               # ReliefSpec, or None for a flat surface
    search_dir: str = ""             # where auto-discovery looked, for error messages

    def to_dict(self) -> dict:
        return {"name": self.name, "display_name": self.display_name,
                "tile_size": self.tile_size, "maps": dict(self.maps),
                "base_color": list(self.base_color), "roughness": self.roughness,
                "metallic": self.metallic, "normal_strength": self.normal_strength,
                "kind": self.kind, "opacity": self.opacity,
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
                   kind=d.get("kind", "opaque"), opacity=float(d.get("opacity", 1.0)),
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


@dataclass(frozen=True)
class FrameSpec:
    """Joinery that actually lines a reveal, rather than a slab dropped in a hole."""

    lining: float = 0.025        # boards lining the reveal, running the full wall depth
    casing: float = 0.060        # flat casing on the wall face; 0 omits it
    casing_depth: float = 0.012  # how far the casing stands proud of the wall
    rebate: float = 0.018        # how far the leaf sits back from the front face
    clearance: float = 0.003     # gap around the leaf so it does not bind

    def to_dict(self) -> dict:
        return {"lining": self.lining, "casing": self.casing,
                "casing_depth": self.casing_depth, "rebate": self.rebate,
                "clearance": self.clearance}

    @classmethod
    def from_dict(cls, d: dict) -> "FrameSpec":
        d = d or {}
        return cls(lining=float(d.get("lining", 0.025)), casing=float(d.get("casing", 0.060)),
                   casing_depth=float(d.get("casing_depth", 0.012)),
                   rebate=float(d.get("rebate", 0.018)),
                   clearance=float(d.get("clearance", 0.003)))


@dataclass(frozen=True)
class AnimationSpec:
    """How the moving part moves. ``kind: none`` means a single static mesh."""

    kind: str = "none"           # none | hinge
    axis: str = "z"
    open_degrees: float = 95.0
    frames: int = 24
    clip: str = "open"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "axis": self.axis, "open_degrees": self.open_degrees,
                "frames": self.frames, "clip": self.clip}

    @classmethod
    def from_dict(cls, d: dict) -> "AnimationSpec":
        d = d or {}
        return cls(kind=d.get("kind", "none"), axis=d.get("axis", "z"),
                   open_degrees=float(d.get("open_degrees", 95.0)),
                   frames=int(d.get("frames", 24)), clip=d.get("clip", "open"))


@dataclass(frozen=True)
class JoinerySpec:
    """A door or window built to fill a named opening.

    Dimensions come from the shared opening rather than from this part's own matrix, so
    the hole and the thing that fills it cannot drift apart.
    """

    id: str
    name: str
    display_name: str
    fits: str                       # the opening's name
    opening: Opening
    wall_thickness: float
    frame: FrameSpec
    slots: dict                     # slot name -> MaterialSpec
    animation: AnimationSpec
    leaf: str = ""                  # panel | plank | glazed   (doors)
    hinge: str = ""                 # left | right             (doors)
    pattern: str = ""               # single | cross | grid    (windows)
    leaf_thickness: float = 0.045
    glazing_bar: float = 0.028
    origin: str = "wall_origin"
    category: str = "Doors"
    tags: tuple = ()
    source: str = "procedural"
    type: str = "door"

    @property
    def material(self) -> MaterialSpec:
        """Primary material, for the manifest and anything expecting a single one."""
        return self.slots.get("frame") or next(iter(self.slots.values()))

    @property
    def clear_width(self) -> float:
        return self.opening.width - 2 * self.frame.lining

    @property
    def clear_height(self) -> float:
        # A door is lined on three sides; a window is lined on four.
        sides = 1 if self.type == "door" else 2
        return self.opening.height - sides * self.frame.lining

    def dimensions(self) -> dict:
        return {"opening_width": self.opening.width, "opening_height": self.opening.height,
                "sill": self.opening.sill, "clear_width": round(self.clear_width, 6),
                "clear_height": round(self.clear_height, 6),
                "wall_thickness": self.wall_thickness, "unit": "m"}

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "source": self.source, "name": self.name,
                "display_name": self.display_name, "fits": self.fits,
                "opening": self.opening.to_dict(), "wall_thickness": self.wall_thickness,
                "frame": self.frame.to_dict(), "animation": self.animation.to_dict(),
                "slots": {k: v.to_dict() for k, v in self.slots.items()},
                "leaf": self.leaf, "hinge": self.hinge, "pattern": self.pattern,
                "leaf_thickness": self.leaf_thickness, "glazing_bar": self.glazing_bar,
                "origin": self.origin, "category": self.category, "tags": list(self.tags)}

    @classmethod
    def from_dict(cls, d: dict) -> "JoinerySpec":
        return cls(id=d["id"], name=d["name"], display_name=d.get("display_name", d["name"]),
                   fits=d["fits"], opening=Opening.from_dict(d["opening"]),
                   wall_thickness=float(d.get("wall_thickness", 0.2)),
                   frame=FrameSpec.from_dict(d.get("frame")),
                   animation=AnimationSpec.from_dict(d.get("animation")),
                   slots={k: MaterialSpec.from_dict(v) for k, v in (d.get("slots") or {}).items()},
                   leaf=d.get("leaf", ""), hinge=d.get("hinge", ""), pattern=d.get("pattern", ""),
                   leaf_thickness=float(d.get("leaf_thickness", 0.045)),
                   glazing_bar=float(d.get("glazing_bar", 0.028)),
                   origin=d.get("origin", "wall_origin"),
                   category=d.get("category", "Doors"), tags=tuple(d.get("tags", [])),
                   source=d.get("source", "procedural"), type=d.get("type", "door"))


@dataclass(frozen=True)
class GableSpec:
    """The triangular wall closing a roof end.

    Carries no openings by design: a gable that needs one is built tall enough to sit
    on a normal wall course, and the opening goes in that wall instead.
    """

    id: str
    name: str
    display_name: str
    shape: str                    # full | left | right
    width: float
    thickness: float
    angle: float                  # degrees, from the SHARED pitch library
    pitch: str
    material: MaterialSpec
    origin: str = "bottom_center"
    category: str = "Walls"
    tags: tuple = ()
    source: str = "procedural"
    type: str = "gable"

    @property
    def apex(self) -> float:
        """Half-span for a centred apex, full span for a half gable."""
        run = self.width / 2.0 if self.shape == "full" else self.width
        return run * math.tan(math.radians(self.angle))

    def dimensions(self) -> dict:
        return {"width": self.width, "apex": round(self.apex, 6),
                "thickness": self.thickness, "pitch_degrees": self.angle, "unit": "m"}

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "source": self.source, "name": self.name,
                "display_name": self.display_name, "shape": self.shape, "width": self.width,
                "thickness": self.thickness, "angle": self.angle, "pitch": self.pitch,
                "material": self.material.to_dict(), "origin": self.origin,
                "category": self.category, "tags": list(self.tags)}

    @classmethod
    def from_dict(cls, d: dict) -> "GableSpec":
        return cls(id=d["id"], name=d["name"], display_name=d.get("display_name", d["name"]),
                   shape=d["shape"], width=float(d["width"]),
                   thickness=float(d.get("thickness", 0.2)), angle=float(d["angle"]),
                   pitch=d.get("pitch", ""), material=MaterialSpec.from_dict(d["material"]),
                   origin=d.get("origin", "bottom_center"),
                   category=d.get("category", "Walls"), tags=tuple(d.get("tags", [])),
                   source=d.get("source", "procedural"), type=d.get("type", "gable"))


@dataclass(frozen=True)
class CornerSpec:
    """An L-shaped wall segment forming a building corner in one mesh.

    Being one mesh is the point: four equal-length walls meeting at a corner put
    coplanar faces against each other and z-fight into black bars. A corner has no
    internal join to fight with.
    """

    id: str
    name: str
    display_name: str
    arm: float                    # length along each side, from the outer corner
    height: float
    thickness: float
    material: MaterialSpec
    origin: str = "outer_corner"
    category: str = "Walls"
    tags: tuple = ()
    source: str = "procedural"
    type: str = "corner"

    def dimensions(self) -> dict:
        return {"arm": self.arm, "height": self.height,
                "thickness": self.thickness, "unit": "m"}

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "source": self.source, "name": self.name,
                "display_name": self.display_name, "arm": self.arm, "height": self.height,
                "thickness": self.thickness, "material": self.material.to_dict(),
                "origin": self.origin, "category": self.category, "tags": list(self.tags)}

    @classmethod
    def from_dict(cls, d: dict) -> "CornerSpec":
        return cls(id=d["id"], name=d["name"], display_name=d.get("display_name", d["name"]),
                   arm=float(d["arm"]), height=float(d["height"]),
                   thickness=float(d.get("thickness", 0.2)),
                   material=MaterialSpec.from_dict(d["material"]),
                   origin=d.get("origin", "outer_corner"),
                   category=d.get("category", "Walls"), tags=tuple(d.get("tags", [])),
                   source=d.get("source", "procedural"), type=d.get("type", "corner"))


GABLE_SHAPES = ("full", "left", "right")

SPEC_TYPES = {"wall": WallSpec, "roof": RoofSpec, "door": JoinerySpec,
              "window": JoinerySpec, "gable": GableSpec, "corner": CornerSpec}


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
    if isinstance(spec, JoinerySpec):
        return _validate_joinery(spec)
    if isinstance(spec, GableSpec):
        if spec.shape not in GABLE_SHAPES:
            return f"unknown gable shape {spec.shape!r}; known: {GABLE_SHAPES}"
        if spec.width <= 0 or spec.thickness <= 0:
            return "non-positive dimension"
        if not 0.0 < spec.angle < 90.0:
            return f"pitch {spec.angle} must be between 0 and 90 degrees"
        return None
    if isinstance(spec, CornerSpec):
        if spec.arm <= spec.thickness:
            return (f"arm {spec.arm}m must exceed the wall thickness "
                    f"{spec.thickness}m or the corner is just a post")
        if spec.height <= 0:
            return "non-positive height"
        return None
    return _validate_wall(spec, min_border)


def _validate_joinery(spec: JoinerySpec):
    """Catch a piece that cannot physically fit here, not in game."""
    if spec.clear_width <= 0 or spec.clear_height <= 0:
        return (f"lining {spec.frame.lining}m leaves no clear opening in a "
                f"{spec.opening.width}x{spec.opening.height}m {spec.fits}")
    if spec.type == "door":
        leaf_w = spec.clear_width - 2 * spec.frame.clearance
        leaf_h = spec.clear_height - 2 * spec.frame.clearance
        if leaf_w <= 0 or leaf_h <= 0:
            return f"clearance {spec.frame.clearance}m leaves no leaf"
        depth = spec.frame.rebate + spec.leaf_thickness
        if depth > spec.wall_thickness:
            return (f"leaf sits {depth:.3f}m into a {spec.wall_thickness}m wall - "
                    f"reduce rebate or leaf_thickness")
    if "frame" not in spec.slots:
        return "no 'frame' material slot"
    # A mistyped style would otherwise fall through to the default and ship a door
    # nobody asked for, which is invisible until someone looks at every thumbnail.
    if spec.type == "door" and spec.leaf not in LEAF_STYLES:
        return f"unknown leaf style {spec.leaf!r}; known: {LEAF_STYLES}"
    if spec.type == "window" and spec.pattern not in WINDOW_PATTERNS:
        return f"unknown glazing pattern {spec.pattern!r}; known: {WINDOW_PATTERNS}"
    return None


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
