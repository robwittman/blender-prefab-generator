"""Load a prefab matrix config and resolve it into concrete specs."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

from . import color
from . import textures as textures_mod
from .ids import DEFAULT_ID_TEMPLATE, make_id
from .matrix import expand, render_name
from .spec import (MAP_ROLES, AnimationSpec, CornerSpec, FrameSpec, GableSpec,
                    JoinerySpec, MaterialSpec, Opening, ReliefSpec, RoofSpec, WallSpec,
                    validate)

DEFAULT_MIN_BORDER = 0.1

PART_TYPES = ("wall", "roof", "door", "window", "gable", "corner")


@dataclass
class Skipped:
    name: str
    reason: str


@dataclass
class Thumbnails:
    enabled: bool = True
    size: int = 512
    samples: int = 48


@dataclass
class Plan:
    out_dir: str
    models_dir: str
    thumbnails_dir: str
    formats: list
    specs: list
    skipped: list
    materials: dict
    thumbnails: Thumbnails
    manifest: str = "manifest.json"
    pack_textures: bool = False
    library: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    excluded: list = field(default_factory=list)   # dropped by --filter, not by the config


INCLUDE_KEY = "include"

# Values under these keys are paths written relative to the config file that declared
# them. The resolver joins every path onto the ROOT config's directory, so anything an
# include contributes has to be re-pointed at that directory or it lands in the wrong
# place the moment a shared config lives in a folder of its own.
_PATH_KEYS = (("output", "dir"), ("textures", "root"))


def load(path: str) -> dict:
    """Load a config file, resolving any ``include:`` it names.

    Includes exist so pieces that must agree - pitches a gable and a roof share,
    openings a wall cuts and a door fills - can be written once and pulled into every
    build that needs them.

    Includes merge in the order listed and the including file wins over all of them:
    mappings merge key by key, anything else (a list, a scalar) replaces outright. So a
    shared file can carry the whole ``parts:`` list, but a config that declares its own
    replaces that list rather than appending to it. Includes may nest; a cycle is an
    error.
    """
    path = os.path.abspath(path)
    return _load(path, os.path.dirname(path), ())


def _load(path: str, root_dir: str, stack: tuple) -> dict:
    if path in stack:
        chain = " -> ".join(os.path.basename(p) for p in stack + (path,))
        raise ValueError(f"include cycle: {chain}")

    cfg = _read(path)
    here = os.path.dirname(path)
    merged = {}
    for rel in _include_list(cfg.pop(INCLUDE_KEY, None), path):
        target = os.path.normpath(os.path.join(here, rel))
        if not os.path.exists(target):
            raise ValueError(f"{os.path.basename(path)} includes {rel!r}, which does "
                             f"not exist (looked in {target})")
        merged = _merge(merged, _load(target, root_dir, stack + (path,)))
    return _merge(merged, _anchor(cfg, here, root_dir))


def _read(path: str) -> dict:
    with open(path, "r") as fh:
        if path.endswith((".yaml", ".yml")):
            import yaml
            cfg = yaml.safe_load(fh)
        else:
            cfg = json.load(fh)
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise ValueError(f"{path}: a config must be a mapping, got {type(cfg).__name__}")
    return cfg


def _include_list(raw, path: str) -> list:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
        return raw
    raise ValueError(f"{path}: 'include' must be a path or a list of paths")


def _merge(base: dict, over: dict) -> dict:
    """Deep-merge mappings key by key; anything else replaces outright."""
    out = dict(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def _anchor(cfg: dict, here: str, root_dir: str) -> dict:
    """Re-express an included file's paths so they still point where it meant."""
    if os.path.normpath(here) == os.path.normpath(root_dir):
        return cfg
    for section, key in _PATH_KEYS:
        block = cfg.get(section)
        if not isinstance(block, dict):
            continue
        val = block.get(key)
        if isinstance(val, str) and not os.path.isabs(val):
            cfg[section] = dict(block)
            cfg[section][key] = os.path.relpath(os.path.join(here, val), root_dir)
    return cfg


def resolve(cfg: dict, base_dir: str = ".") -> Plan:
    out = cfg.get("output", {}) or {}
    out_dir = os.path.normpath(os.path.join(base_dir, out.get("dir", "build")))
    fmt = out.get("format", "blend")
    formats = [fmt] if isinstance(fmt, str) else list(fmt)

    thumb_cfg = out.get("thumbnails", {}) or {}
    thumbs = Thumbnails(enabled=bool(thumb_cfg.get("enabled", True)),
                        size=int(thumb_cfg.get("size", 512)),
                        samples=int(thumb_cfg.get("samples", 48)))

    tex_root = os.path.normpath(os.path.join(base_dir, (cfg.get("textures", {}) or {}).get("root", "textures")))
    materials, warnings = _materials(cfg.get("materials", {}) or {}, tex_root)

    raw_defaults = cfg.get("defaults", {}) or {}

    specs, skipped, seen_ids, seen_names = [], [], {}, set()

    # Pitches are a shared library like materials and openings. Gables live with the
    # walls and roofs live in their own config, but both must use the identical angle
    # or a gable will not meet the roof it is closing.
    pitch_src = dict(cfg.get("pitches") or {})
    pitch_src.update((cfg.get("roof") or {}).get("pitches") or {})
    pitches = _pitches({"pitches": pitch_src})
    openings = _openings(cfg.get("openings", {}) or {})

    for part in cfg.get("parts", []) or []:
        ptype = part.get("type", "wall")
        if ptype not in PART_TYPES:
            raise ValueError(f"unsupported part type {ptype!r} "
                             f"(known: {', '.join(PART_TYPES)})")
        defaults = _defaults_for(raw_defaults, ptype)
        min_border = float(defaults.get("min_border", DEFAULT_MIN_BORDER))
        source = part.get("source", defaults.get("source", "procedural"))
        if source != "procedural":
            raise ValueError(f"unsupported source {source!r} (only 'procedural' so far)")

        template = part["name"]
        display_tpl = part.get("display_name", template)
        id_tpl = part.get("id_template", defaults.get("id_template", DEFAULT_ID_TEMPLATE))
        base_tags = list(part.get("tags", []))

        for combo in expand(part.get("matrix", {}), part.get("exclude")):
            # Part-level constants join the axes for naming, so a piece kind that is
            # fixed for the whole part still reaches {piece} in names and ids.
            fields = dict(combo)
            if ptype == "roof":
                fields["piece"] = part["piece"]
            if ptype == "corner":
                fields["arm_mm"] = int(round(float(part.get("arm", 1.0)) * 1000))
            if ptype in ("door", "window"):
                fits = part.get("fits")
                if fits not in openings or openings[fits] is None:
                    raise ValueError(f"{ptype} part 'fits: {fits!r}' is not a defined "
                                     f"opening (known: {sorted(k for k, v in openings.items() if v)})")
                fields["fits"] = fits
                fields["opening_w_mm"] = int(round(openings[fits].width * 1000))
                fields["opening_h_mm"] = int(round(openings[fits].height * 1000))

            name = render_name(template, fields)
            pid = make_id(ptype, fields, id_tpl)
            if pid in seen_ids:
                raise ValueError(f"duplicate prefab id {pid!r} (also produced by {seen_ids[pid]!r}) "
                                 "- widen id_template or the matrix")
            if name in seen_names:
                raise ValueError(f"duplicate prefab name {name!r} - widen the name template")
            seen_ids[pid] = name
            seen_names.add(name)

            mat = _lookup_material(materials, combo.get("material"), defaults)
            common = dict(
                id=pid, name=name,
                display_name=_titlecase(render_name(display_tpl, fields)),
                material=mat, source=source,
                tags=tuple(base_tags + [str(v) for k, v in fields.items() if isinstance(v, str)]),
            )

            if ptype == "wall":
                spec = _wall_spec(part, defaults, combo, materials, common, openings)
            elif ptype == "roof":
                spec = _roof_spec(part, defaults, combo, pitches, common)
            elif ptype == "gable":
                spec = _gable_spec(part, defaults, combo, pitches, common)
            elif ptype == "corner":
                spec = _corner_spec(part, defaults, combo, common)
            else:
                spec = _joinery_spec(part, defaults, combo, openings, materials, common)

            reason = validate(spec, min_border)
            (skipped.append(Skipped(name, reason)) if reason else specs.append(spec))

    return Plan(out_dir=out_dir,
                models_dir=out.get("models_dir", "models"),
                thumbnails_dir=out.get("thumbnails_dir", "thumbnails"),
                formats=formats, specs=specs, skipped=skipped, materials=materials,
                thumbnails=thumbs, manifest=out.get("manifest", "manifest.json"),
                pack_textures=bool(out.get("pack_textures", False)),
                library=cfg.get("library", {}) or {}, warnings=warnings)


def _defaults_for(raw: dict, ptype: str) -> dict:
    """The defaults block, flattened for one part type.

    ``thickness`` means 0.2 to a wall and 0.18 to a roof; ``origin`` means
    bottom_center to a wall and footprint_center to a roof. A single flat block cannot
    carry both, so a shared config pulled into a walls kit AND a roofs kit collides on
    the key rather than sharing it.

    Nesting a block under a part type qualifies the key. Unqualified keys still apply
    to every part - that is where genuinely cross-cutting settings like ``min_border``
    belong - and the type block wins for parts of that type:

        defaults:
          min_border: 0.1                        # every part
          wall: { thickness: 0.2 }               # walls only
          roof: { thickness: 0.18 }              # roofs only
    """
    flat = {k: v for k, v in raw.items() if k not in PART_TYPES}
    scoped = raw.get(ptype)
    if scoped is None:
        return flat
    if not isinstance(scoped, dict):
        raise ValueError(f"defaults.{ptype} must be a mapping of default values "
                         f"for {ptype} parts, got {type(scoped).__name__}")
    flat.update(scoped)
    return flat


def _openings(raw: dict) -> dict:
    """The shared opening library. Walls cut these; joinery fills them."""
    out = {}
    for name, entry in raw.items():
        out[name] = None if entry is None else Opening.from_dict({"kind": name, **entry})
    return out


def _joinery_spec(part, defaults, combo, openings, materials, common):
    ptype = part.get("type", "door")
    opening = openings[part["fits"]]
    slots = {}
    for slot, ref in (part.get("slots") or {}).items():
        name = ref.format(**combo) if isinstance(ref, str) else ref
        slots[slot] = _lookup_material(materials, name, defaults)

    common = dict(common)
    common.pop("material", None)          # joinery carries a slot map, not one material
    return JoinerySpec(
        fits=part["fits"], opening=opening,
        wall_thickness=float(part.get("wall_thickness",
                                      defaults.get("wall_thickness", 0.2))),
        frame=FrameSpec.from_dict(part.get("frame")),
        animation=AnimationSpec.from_dict(part.get("animation")),
        slots=slots,
        leaf=str(combo.get("leaf", "")), hinge=str(combo.get("hinge", "")),
        pattern=str(combo.get("pattern", "")),
        leaf_thickness=float(part.get("leaf_thickness", 0.045)),
        glazing_bar=float(part.get("glazing_bar", 0.028)),
        origin=part.get("origin", defaults.get("origin", "wall_origin")),
        category=part.get("category", "Doors" if ptype == "door" else "Windows"),
        type=ptype, **common)


def _gable_spec(part, defaults, combo, pitches, common):
    pitch = combo.get("pitch")
    if pitch not in pitches:
        raise ValueError(f"pitch {pitch!r} is not defined under 'pitches' "
                         f"(known: {sorted(pitches)})")
    return GableSpec(
        shape=str(combo.get("shape", "full")), width=float(combo["width"]),
        thickness=float(combo.get("thickness", defaults.get("thickness", 0.2))),
        angle=pitches[pitch], pitch=pitch,
        origin=part.get("origin", defaults.get("origin", "bottom_center")),
        category=part.get("category", "Walls"), type="gable", **common)


def _corner_spec(part, defaults, combo, common):
    return CornerSpec(
        arm=float(part.get("arm", 1.0)), height=float(combo["height"]),
        thickness=float(combo.get("thickness", defaults.get("thickness", 0.2))),
        origin=part.get("origin", "outer_corner"),
        category=part.get("category", "Walls"), type="corner", **common)


def _pitches(raw: dict) -> dict:
    """Named pitches, so pieces that must physically meet cannot drift apart.

    A pitch may be given as ``angle`` in degrees, or as a ``rise``/``run`` ratio. Prefer
    the ratio for anything meant to land on the grid: writing 26.565 degrees for a 1:2
    pitch is a rounded decimal, and a 2m run then rises 0.999998m rather than exactly
    1m - harmless to look at, but it is the kind of drift a modular kit exists to avoid.
    """
    out = {}
    for name, entry in (raw.get("pitches", {}) or {}).items():
        if not isinstance(entry, dict):
            out[name] = float(entry)
            continue
        if "rise" in entry or "run" in entry:
            rise, run = float(entry.get("rise", 1.0)), float(entry.get("run", 1.0))
            if run <= 0:
                raise ValueError(f"pitch {name!r}: run must be positive")
            out[name] = math.degrees(math.atan(rise / run))
        elif entry.get("angle") is not None:
            out[name] = float(entry["angle"])
        else:
            raise ValueError(f"pitch {name!r} needs an angle, or a rise and run")
    return out


def _wall_spec(part, defaults, combo, materials, common, shared=None):
    reveal_name = part.get("reveal_material", defaults.get("reveal_material"))
    return WallSpec(
        width=float(combo["width"]), height=float(combo["height"]),
        thickness=float(combo.get("thickness", defaults.get("thickness", 0.2))),
        openings=_openings_for(combo, part.get("openings", {}) or {}, shared),
        reveal_material=materials[reveal_name] if reveal_name else None,
        origin=part.get("origin", defaults.get("origin", "bottom_center")),
        category=part.get("category", "Walls"), type="wall", **common)


def _roof_spec(part, defaults, combo, pitches, common):
    piece = part["piece"]
    pitch = combo.get("pitch")
    if pitch not in pitches:
        raise ValueError(f"pitch {pitch!r} is not defined under roof.pitches "
                         f"(known: {sorted(pitches)})")
    run = float(combo.get("run", 0.0))
    # Corners are square in plan, and a ridge's footprint depth is its cap width.
    span = float(combo.get("span", run))
    cap_width = float(part.get("cap_width", defaults.get("cap_width", 0.30)))
    if piece == "ridge":
        run = cap_width
    return RoofSpec(
        piece=piece, angle=pitches[pitch], pitch=pitch, span=span, run=run,
        thickness=float(combo.get("thickness", defaults.get("thickness", 0.18))),
        cap_width=cap_width,
        cap_thickness=float(part.get("cap_thickness", defaults.get("cap_thickness", 0.06))),
        origin=part.get("origin", defaults.get("origin", "footprint_center")),
        category=part.get("category", "Roofs"), type="roof", **common)


def _titlecase(s: str) -> str:
    """Capitalise the first character only - .title() would mangle '2.5m'."""
    return s[:1].upper() + s[1:]


def _materials(raw: dict, tex_root: str):
    """Resolve every material's texture maps.

    Precedence per role: an explicit ``maps:`` entry wins, otherwise whatever the
    folder scan found. ``dir:`` points at a folder other than the material name, so an
    ambientCG zip can be unpacked as-is. An explicit ``null`` suppresses a role.
    """
    out, warnings = {}, []
    for name, m in raw.items():
        m = m or {}
        folder = os.path.normpath(os.path.join(tex_root, m.get("dir", name)))
        maps, flip_green, ambiguous = textures_mod.scan(folder)
        for role in ambiguous:
            warnings.append(f"{name}: several files could be the {role} map in {folder}; "
                            f"picked {os.path.basename(maps[role])} - set maps.{role} to override")

        for role, rel in (m.get("maps") or {}).items():
            if role not in MAP_ROLES:
                raise ValueError(f"material {name!r}: unknown map role {role!r}; known: {MAP_ROLES}")
            if not rel:
                maps.pop(role, None)          # explicit null suppresses a discovered map
            else:
                maps[role] = _resolve_map(rel, folder, tex_root)

        out[name] = MaterialSpec(
            name=name, display_name=m.get("display_name", name.replace("_", " ").title()),
            tile_size=float(m.get("tile_size", 1.0)), maps=maps,
            base_color=color.parse(m.get("base_color")),
            kind=m.get("kind", "opaque"),
            opacity=float(m.get("opacity", 1.0)),
            roughness=float(m.get("roughness", 0.8)),
            metallic=float(m.get("metallic", 0.0)),
            normal_strength=float(m.get("normal_strength", 1.0)),
            normal_flip_green=bool(m.get("normal_flip_green", flip_green)),
            search_dir=folder, relief=_relief(name, m.get("relief"), maps, warnings))
    return out, warnings


def _relief(name: str, raw, maps: dict, warnings: list):
    """Relief needs a height map; asking for it without one is a warning, not a failure."""
    if not raw:
        return None
    if raw is True:
        raw = {}
    if "height" not in maps:
        warnings.append(f"{name}: relief requested but no height/displacement map was "
                        f"found - the surface will stay flat")
        return None
    return ReliefSpec.from_dict(raw)


def _resolve_map(rel: str, folder: str, tex_root: str) -> str:
    """Accept an absolute path, one relative to the material folder, or to textures/."""
    if os.path.isabs(rel):
        return os.path.normpath(rel)
    in_folder = os.path.normpath(os.path.join(folder, rel))
    if os.path.exists(in_folder):
        return in_folder
    in_root = os.path.normpath(os.path.join(tex_root, rel))
    return in_root if os.path.exists(in_root) else in_folder


def _lookup_material(materials: dict, key, defaults: dict) -> MaterialSpec:
    key = key or defaults.get("material")
    if key is None:
        return MaterialSpec(name="Default", display_name="Default")
    if key not in materials:
        raise ValueError(f"material {key!r} is not defined under 'materials' "
                         f"(known: {sorted(materials)})")
    return materials[key]


def _openings_for(combo: dict, presets: dict, shared: dict = None) -> tuple:
    """Part-local presets win; anything else resolves against the shared library."""
    key = combo.get("opening")
    if key is None:
        return ()
    merged = dict(shared or {})
    merged.update(presets)
    if key not in merged:
        raise ValueError(f"opening {key!r} is not defined locally or under the "
                         f"top-level 'openings' (known: {sorted(merged)})")
    preset = merged[key]
    if preset is None:
        return ()
    if isinstance(preset, Opening):
        return (preset,)
    entries = preset if isinstance(preset, list) else [preset]
    return tuple(Opening.from_dict({"kind": key, **e}) for e in entries)
