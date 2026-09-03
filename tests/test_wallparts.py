import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prefabgen.config import resolve

SHALLOW = math.degrees(math.atan(0.5))


def _cfg(parts, **over):
    cfg = {
        "output": {"dir": "build"},
        "textures": {"root": "textures"},
        "pitches": {"shallow": {"rise": 1, "run": 2}, "steep": {"rise": 1, "run": 1}},
        "materials": {"planks": {"base_color": "#8a6a43"}},
        "defaults": {"thickness": 0.2},
        "parts": parts,
    }
    cfg.update(over)
    return cfg


def _gable(**matrix):
    base = {"width": [4], "shape": ["full"], "pitch": ["steep"], "material": ["planks"]}
    base.update(matrix)
    return [{"type": "gable", "name": "gable_{width}_{shape}_{pitch}_{material}",
             "id_template": "{type}.{width_mm}.{shape}.{pitch}.{material}", "matrix": base}]


# --- gables -----------------------------------------------------------------

def _close(got, want):
    # tan(radians(45)) is 0.9999999999999999, so exact equality is the wrong test;
    # 1e-9 is still four orders below Blender's float32 vertex precision.
    return abs(got - want) < 1e-9


def test_apex_uses_half_span_for_a_centred_gable_and_full_span_for_a_half():
    specs = {s.shape: s for s in resolve(_cfg(_gable(shape=["full", "left", "right"]))).specs}
    assert _close(specs["full"].apex, 2.0)      # 4m wide, apex centred, 1:1
    assert _close(specs["left"].apex, 4.0)      # apex at one end, so the full span rises
    assert _close(specs["right"].apex, 4.0)


def test_every_apex_lands_on_the_grid_at_both_pitches():
    plan = resolve(_cfg(_gable(width=[1, 2, 4], pitch=["shallow", "steep"])))
    for spec in plan.specs:
        assert abs(spec.apex * 4 - round(spec.apex * 4)) < 1e-9, spec.name


def test_gable_pitch_comes_from_the_shared_library_not_a_restated_angle():
    spec = resolve(_cfg(_gable(pitch=["shallow"]))).specs[0]
    assert abs(spec.angle - SHALLOW) < 1e-12
    assert abs(spec.apex - 1.0) < 1e-9          # 4m wide, centred apex, 1:2


def test_pitches_may_still_come_from_the_roof_block():
    cfg = _cfg(_gable())
    cfg["roof"] = {"pitches": cfg.pop("pitches")}
    assert _close(resolve(cfg).specs[0].apex, 2.0)


def test_unknown_gable_shape_is_rejected():
    plan = resolve(_cfg(_gable(shape=["wedge"])))
    assert plan.specs == [] and "unknown gable shape" in plan.skipped[0].reason


def test_unknown_pitch_is_an_error():
    try:
        resolve(_cfg(_gable(pitch=["vertiginous"])))
    except ValueError as exc:
        assert "vertiginous" in str(exc)
    else:
        raise AssertionError("expected an unknown-pitch error")


# --- corners ----------------------------------------------------------------

def _corner(arm=1.0, heights=(2.5,)):
    return [{"type": "corner", "arm": arm, "name": "corner_{height}_{material}",
             "id_template": "{type}.{arm_mm}x{height_mm}.{material}",
             "matrix": {"height": list(heights), "material": ["planks"]}}]


def test_corner_carries_its_arm_length_and_reports_dimensions():
    spec = resolve(_cfg(_corner())).specs[0]
    assert spec.arm == 1.0 and spec.height == 2.5
    assert spec.dimensions() == {"arm": 1.0, "height": 2.5, "thickness": 0.2, "unit": "m"}


def test_corner_id_records_the_arm_so_a_resize_is_visible():
    assert resolve(_cfg(_corner())).specs[0].id == "corner.1000x2500.planks"


def test_an_arm_shorter_than_the_wall_thickness_is_rejected():
    plan = resolve(_cfg(_corner(arm=0.15)))
    assert plan.specs == [] and "must exceed the wall thickness" in plan.skipped[0].reason


def test_corner_anchors_on_its_outer_corner_not_its_centre():
    # Placement relies on this: the outer corner is what lands on the building corner.
    assert resolve(_cfg(_corner())).specs[0].origin == "outer_corner"


def test_specs_round_trip_through_json():
    from prefabgen.spec import CornerSpec, GableSpec, spec_from_dict
    for parts, kind in ((_gable(), GableSpec), (_corner(), CornerSpec)):
        spec = resolve(_cfg(parts)).specs[0]
        back = spec_from_dict(spec.to_dict())
        assert isinstance(back, kind) and back.id == spec.id
        assert back.dimensions() == spec.dimensions()
