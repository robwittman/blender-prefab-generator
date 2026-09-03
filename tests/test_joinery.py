import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prefabgen.config import resolve
from prefabgen.spec import JoinerySpec, validate


def _cfg(**over):
    cfg = {
        "output": {"dir": "build"},
        "textures": {"root": "textures"},
        "openings": {"door": {"width": 0.9, "height": 2.1, "sill": 0.0},
                     "window": {"width": 1.2, "height": 1.2, "sill": 1.0}},
        "materials": {"oak": {"base_color": "#7a5a34"},
                      "iron": {"base_color": "#3b3b3f", "metallic": 1.0},
                      "glazing": {"kind": "glass", "opacity": 0.22}},
        "defaults": {"wall_thickness": 0.2},
        "parts": [{
            "type": "door", "fits": "door",
            "name": "door_{leaf}_{hinge}_{material}",
            "id_template": "{type}.{opening_w_mm}x{opening_h_mm}.{leaf}.{hinge}.{material}",
            "frame": {"lining": 0.025, "clearance": 0.003, "rebate": 0.018},
            "slots": {"frame": "{material}", "leaf": "{material}", "hardware": "iron"},
            "animation": {"kind": "hinge", "open_degrees": 95},
            "matrix": {"leaf": ["braced"], "hinge": ["left", "right"], "material": ["oak"]},
        }],
    }
    cfg.update(over)
    return cfg


# --- the shared opening library ---------------------------------------------

def test_joinery_takes_its_size_from_the_shared_opening():
    spec = resolve(_cfg()).specs[0]
    assert (spec.opening.width, spec.opening.height) == (0.9, 2.1)
    assert spec.clear_width == 0.9 - 2 * 0.025      # lined both jambs
    assert spec.clear_height == 2.1 - 0.025         # a door is lined on three sides


def test_a_window_is_lined_on_four_sides():
    cfg = _cfg()
    cfg["parts"][0].update(type="window", fits="window", pattern=None,
                           matrix={"pattern": ["cross"], "material": ["oak"]},
                           name="window_{pattern}_{material}",
                           id_template="{type}.{opening_w_mm}x{opening_h_mm}.{pattern}.{material}")
    spec = resolve(cfg).specs[0]
    assert spec.clear_height == 1.2 - 2 * 0.025


def test_fitting_an_undefined_opening_is_an_error():
    cfg = _cfg()
    cfg["parts"][0]["fits"] = "hatch"
    try:
        resolve(cfg)
    except ValueError as exc:
        assert "hatch" in str(exc)
    else:
        raise AssertionError("expected an unknown-opening error")


def test_walls_resolve_openings_against_the_shared_library():
    cfg = _cfg()
    cfg["parts"] = [{"type": "wall", "name": "w_{width}_{opening}_{material}",
                     "openings": {"solid": None},          # only 'solid' is part-local
                     "matrix": {"width": [4], "height": [2.5], "thickness": [0.2],
                                "opening": ["solid", "door"], "material": ["oak"]}}]
    specs = {s.name: s for s in resolve(cfg).specs}
    assert specs["w_4_solid_oak"].openings == ()
    assert specs["w_4_door_oak"].openings[0].width == 0.9   # came from the shared library


# --- fit and slots ----------------------------------------------------------

def test_leaf_that_cannot_fit_the_wall_depth_is_rejected():
    cfg = _cfg()
    cfg["parts"][0]["leaf_thickness"] = 0.30       # deeper than the 0.2m wall
    plan = resolve(cfg)
    assert plan.specs == []
    assert any("into a 0.2m wall" in s.reason for s in plan.skipped)


def test_lining_that_swallows_the_opening_is_rejected():
    cfg = _cfg()
    cfg["parts"][0]["frame"]["lining"] = 0.5
    plan = resolve(cfg)
    assert plan.specs == [] and "no clear opening" in plan.skipped[0].reason


def test_slot_templates_resolve_per_combination():
    spec = resolve(_cfg()).specs[0]
    assert spec.slots["frame"].name == "oak" and spec.slots["leaf"].name == "oak"
    assert spec.slots["hardware"].name == "iron"
    assert spec.material.name == "oak"             # primary, for the manifest


def test_glass_is_a_material_kind_not_a_texture_set():
    mats = resolve(_cfg()).materials
    assert mats["glazing"].kind == "glass" and mats["glazing"].opacity == 0.22
    assert mats["oak"].kind == "opaque" and mats["oak"].opacity == 1.0


# --- handedness and animation ----------------------------------------------

def test_both_hands_are_generated_and_carry_the_animation_contract():
    specs = {s.hinge: s for s in resolve(_cfg()).specs}
    assert set(specs) == {"left", "right"}
    for spec in specs.values():
        assert spec.animation.kind == "hinge" and spec.animation.open_degrees == 95
        assert spec.animation.clip == "open"


def test_ids_carry_the_opening_size_so_a_resize_is_visible():
    spec = resolve(_cfg()).specs[0]
    assert spec.id == "door.900x2100.braced.left.oak"


def test_a_mistyped_leaf_style_is_rejected_not_silently_defaulted():
    cfg = _cfg()
    cfg["parts"][0]["matrix"]["leaf"] = ["pannel"]
    plan = resolve(cfg)
    assert plan.specs == [] and "unknown leaf style" in plan.skipped[0].reason


def test_a_static_part_declares_no_animation():
    cfg = _cfg()
    cfg["parts"][0]["animation"] = {"kind": "none"}
    assert resolve(cfg).specs[0].animation.kind == "none"


def test_round_trip_through_json_preserves_the_spec():
    from prefabgen.spec import spec_from_dict
    spec = resolve(_cfg()).specs[0]
    back = spec_from_dict(spec.to_dict())
    assert isinstance(back, JoinerySpec)
    assert back.id == spec.id and back.hinge == spec.hinge
    assert back.clear_width == spec.clear_width
    assert sorted(back.slots) == sorted(spec.slots)
    assert validate(back) is None
