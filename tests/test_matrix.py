import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prefabgen import color
from prefabgen.config import resolve
from prefabgen.ids import make_id
from prefabgen.manifest import compose
from prefabgen.matrix import expand, fmt, render_name
from prefabgen.spec import MaterialSpec, Opening, WallSpec, validate


def _cfg(**over):
    cfg = {
        "output": {"dir": "build"},
        "textures": {"root": "textures"},
        "materials": {"brick": {"base_color": "#8a3b2a", "tile_size": 2.0},
                      "wood": {"display_name": "Wood Planks"}},
        "parts": [{
            "type": "wall",
            "name": "wall_{width}x{height}_{opening}_{material}",
            "matrix": {"width": [1, 4], "height": [2.5], "thickness": [0.2],
                       "opening": ["door"], "material": ["brick", "wood"]},
            "openings": {"door": {"width": 0.9, "height": 2.1}},
        }],
    }
    cfg.update(over)
    return cfg


# --- matrix expansion -------------------------------------------------------

def test_expand_is_ordered_cartesian_product():
    assert expand({"w": [1, 2], "h": [3, 4]}) == [
        {"w": 1, "h": 3}, {"w": 1, "h": 4}, {"w": 2, "h": 3}, {"w": 2, "h": 4}]


def test_exclude_matches_partial_combination():
    combos = expand({"w": [1, 2], "o": ["solid", "door"]}, exclude=[{"w": 1, "o": "door"}])
    assert {"w": 1, "o": "door"} not in combos and len(combos) == 3


def test_exclude_accepts_a_list_of_values():
    assert expand({"w": [1, 2, 4]}, exclude=[{"w": [1, 4]}]) == [{"w": 2}]


def test_names_strip_trailing_zeros():
    assert fmt(4.0) == "4" and fmt(2.50) == "2.5"
    assert render_name("wall_{w}x{h}", {"w": 2.0, "h": 2.5}) == "wall_2x2.5"


# --- stable ids -------------------------------------------------------------

PRETTY = "{type}.{width_mm}x{height_mm}x{thickness_mm}.{opening}.{material}"


def test_id_uses_millimetres_so_float_spelling_cannot_drift():
    combo_a = {"width": 2.5, "height": 4, "thickness": 0.2, "opening": "door", "material": "brick"}
    combo_b = {"width": 2.50, "height": 4.0, "thickness": 0.2, "opening": "door", "material": "brick"}
    assert make_id("wall", combo_a, PRETTY) == make_id("wall", combo_b, PRETTY) == \
        "wall.2500x4000x200.door.brick"


def test_id_defaults_to_the_declared_axes_so_new_part_types_need_no_template():
    assert make_id("floor", {"width": 2, "depth": 2, "material": "wood"}) == "floor.2000.2000.wood"


def test_id_is_independent_of_the_display_name_template():
    plan_a = resolve(_cfg())
    cfg_b = _cfg()
    cfg_b["parts"][0]["name"] = "totally_different_{width}_{height}_{opening}_{material}"
    ids_a = sorted(s.id for s in plan_a.specs)
    ids_b = sorted(s.id for s in resolve(cfg_b).specs)
    assert ids_a == ids_b


def test_duplicate_ids_are_rejected():
    cfg = _cfg()
    cfg["parts"][0]["id_template"] = "{type}.{opening}"   # collapses the whole matrix
    try:
        resolve(cfg)
    except ValueError as exc:
        assert "duplicate prefab id" in str(exc)
    else:
        raise AssertionError("expected a duplicate-id error")


# --- materials --------------------------------------------------------------

def test_material_with_no_texture_files_resolves_to_no_maps():
    plan = resolve(_cfg())
    brick = plan.materials["brick"]
    assert brick.maps == {}
    assert brick.search_dir.endswith(os.path.join("textures", "brick"))


def test_unknown_material_is_an_error():
    cfg = _cfg()
    cfg["parts"][0]["matrix"]["material"] = ["granite"]
    try:
        resolve(cfg)
    except ValueError as exc:
        assert "granite" in str(exc)
    else:
        raise AssertionError("expected an unknown-material error")


def test_missing_textures_are_not_fatal():
    plan = resolve(_cfg())
    assert len(plan.specs) == 2   # still resolves fine without any texture files


def test_hex_colour_converts_to_linear():
    r, g, b, a = color.parse("#ffffff")
    assert (round(r, 4), round(g, 4), round(b, 4), a) == (1.0, 1.0, 1.0, 1.0)
    assert color.parse("#000000") == (0.0, 0.0, 0.0, 1.0)
    assert color.parse("#808080")[0] < 0.5   # sRGB midpoint is ~0.216 linear


def test_display_name_capitalises_without_mangling_decimals():
    plan = resolve(_cfg(**{"parts": [dict(_cfg()["parts"][0],
                                          display_name="{material} wall {width}x{height}")]}))
    assert plan.specs[0].display_name == "Brick wall 4x2.5"


# --- geometry validation ----------------------------------------------------

def test_openings_that_do_not_fit_are_skipped_with_a_reason():
    plan = resolve(_cfg())
    assert [s.name for s in plan.specs] == ["wall_4x2.5_door_brick", "wall_4x2.5_door_wood"]
    assert {s.name for s in plan.skipped} == {"wall_1x2.5_door_brick", "wall_1x2.5_door_wood"}


def test_opening_bounds_are_centred_then_offset():
    assert Opening("door", 1.0, 2.0, sill=0.0, offset=0.5).bounds(4.0) == (2.0, 3.0, 0.0, 2.0)


def test_overlapping_openings_are_rejected():
    spec = WallSpec(id="x", name="w", display_name="W", width=4.0, height=3.0, thickness=0.2,
                    material=MaterialSpec("m"), openings=(
                        Opening("door", 1.0, 2.0, offset=-0.2),
                        Opening("window", 1.0, 1.0, sill=0.5, offset=0.2)))
    assert "overlap" in validate(spec)


# --- manifest ---------------------------------------------------------------

def test_manifest_is_sorted_by_id_and_lists_only_used_materials():
    plan = resolve(_cfg())
    report = {"prefabs": [{"id": s.id, "files": {"blend": os.path.join(plan.out_dir, "models", s.name + ".blend")}}
                          for s in plan.specs]}
    m = compose(plan, report)
    assert [p["id"] for p in m["prefabs"]] == sorted(p["id"] for p in m["prefabs"])
    assert m["counts"]["prefabs"] == 2
    assert {mat["id"] for mat in m["materials"]} == {"brick", "wood"}
    assert m["prefabs"][0]["files"]["blend"].startswith("models/")


def test_manifest_carries_dimensions_and_openings_for_the_picker():
    plan = resolve(_cfg())
    entry = compose(plan, {"prefabs": []})["prefabs"][0]
    assert entry["dimensions"] == {"width": 4.0, "height": 2.5, "thickness": 0.2, "unit": "m"}
    assert entry["openings"][0]["kind"] == "door"
    assert entry["category"] == "Walls"
