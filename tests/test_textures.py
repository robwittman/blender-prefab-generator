import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prefabgen.config import resolve
from prefabgen.textures import classify, scan


def _make(root, *relpaths):
    for rel in relpaths:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
    return root


AMBIENTCG = ["Bricks075A_2K-JPG_Color.jpg", "Bricks075A_2K-JPG_NormalGL.jpg",
             "Bricks075A_2K-JPG_NormalDX.jpg", "Bricks075A_2K-JPG_Roughness.jpg",
             "Bricks075A_2K-JPG_AmbientOcclusion.jpg", "Bricks075A_2K-JPG_Displacement.jpg"]


# --- filename classification ------------------------------------------------

def test_classify_handles_ambientcg_names():
    assert classify("Bricks075A_2K-JPG_Color.jpg") == ("albedo", False)
    assert classify("Bricks075A_2K-JPG_NormalGL.jpg") == ("normal", False)
    assert classify("Bricks075A_2K-JPG_Roughness.jpg") == ("roughness", False)
    assert classify("Bricks075A_2K-JPG_AmbientOcclusion.jpg") == ("ao", False)


POLYHAVEN = ["brick_4_diff_4k.jpg", "brick_4_nor_gl_4k.jpg", "brick_4_nor_dx_4k.jpg",
             "brick_4_rough_4k.jpg", "brick_4_ao_4k.jpg", "brick_4_disp_4k.jpg"]


def test_classify_handles_polyhaven_names_with_the_map_type_in_the_middle():
    # The trailing token is the resolution, not the map type.
    assert classify("brick_4_diff_4k.jpg") == ("albedo", False)
    assert classify("brick_4_rough_4k.jpg") == ("roughness", False)
    assert classify("brick_4_ao_4k.jpg") == ("ao", False)


def test_classify_reads_polyhavens_split_normal_convention_tokens():
    # "nor_gl" / "nor_dx" must not collapse to a bare, convention-less "nor".
    assert classify("brick_4_nor_gl_4k.jpg") == ("normal", False)
    assert classify("brick_4_nor_dx_4k.jpg") == ("normal", True)


def test_scan_of_a_polyhaven_folder_resolves_every_role():
    with tempfile.TemporaryDirectory() as d:
        _make(d, *POLYHAVEN)
        maps, flip, ambiguous = scan(d)
        assert {r: os.path.basename(p) for r, p in maps.items()} == {
            "albedo": "brick_4_diff_4k.jpg", "normal": "brick_4_nor_gl_4k.jpg",
            "roughness": "brick_4_rough_4k.jpg", "ao": "brick_4_ao_4k.jpg",
            "height": "brick_4_disp_4k.jpg"}
        assert flip is False           # the GL sibling was preferred
        assert ambiguous == ["normal"]


def test_classify_flags_directx_normals():
    assert classify("Wood_NormalDX.png") == ("normal", True)


def test_classify_recognises_height_maps_used_for_relief():
    assert classify("Bricks075A_2K-JPG_Displacement.jpg") == ("height", False)
    assert classify("brick_4_disp_4k.jpg") == ("height", False)
    assert classify("height.png") == ("height", False)


def test_classify_ignores_maps_we_do_not_consume():
    assert classify("Bricks075A_2K-JPG_Specular.jpg") == (None, False)
    assert classify("preview.txt") == (None, False)


def test_classify_still_accepts_the_plain_convention():
    assert classify("albedo.png") == ("albedo", False)
    assert classify("roughness.png") == ("roughness", False)


# --- folder scanning --------------------------------------------------------

def test_scan_prefers_opengl_normals_when_both_conventions_are_present():
    with tempfile.TemporaryDirectory() as d:
        _make(d, *AMBIENTCG)
        maps, flip, ambiguous = scan(d)
        assert os.path.basename(maps["normal"]) == "Bricks075A_2K-JPG_NormalGL.jpg"
        assert flip is False
        assert ambiguous == ["normal"]        # user is told the choice was made for them
        assert set(maps) == {"albedo", "normal", "roughness", "ao", "height"}


def test_scan_falls_back_to_directx_and_reports_the_flip():
    with tempfile.TemporaryDirectory() as d:
        _make(d, "Cedar_Color.png", "Cedar_NormalDX.png")
        maps, flip, _ = scan(d)
        assert os.path.basename(maps["normal"]) == "Cedar_NormalDX.png"
        assert flip is True


def test_scan_finds_textures_left_inside_an_unzipped_subfolder():
    with tempfile.TemporaryDirectory() as d:
        _make(d, os.path.join("WoodFloor041_2K-JPG", "WoodFloor041_2K-JPG_Color.jpg"))
        maps, _, _ = scan(d)
        assert maps["albedo"].endswith(os.path.join("WoodFloor041_2K-JPG", "WoodFloor041_2K-JPG_Color.jpg"))


def test_scan_of_a_missing_folder_is_empty_not_an_error():
    assert scan("/nope/does/not/exist") == ({}, False, [])


# --- config precedence ------------------------------------------------------

def _cfg(root, materials):
    return {"output": {"dir": "build"}, "textures": {"root": root},
            "materials": materials,
            "parts": [{"type": "wall", "name": "w_{width}_{material}",
                       "matrix": {"width": [4], "height": [2.5], "thickness": [0.2],
                                  "material": list(materials)}}]}


def test_explicit_map_overrides_discovery_but_keeps_the_rest():
    with tempfile.TemporaryDirectory() as d:
        _make(d, *[os.path.join("brick", f) for f in AMBIENTCG])
        _make(d, os.path.join("brick", "hand_authored_albedo.png"))
        plan = resolve(_cfg(d, {"brick": {"maps": {"albedo": "hand_authored_albedo.png"}}}))
        m = plan.materials["brick"]
        assert os.path.basename(m.maps["albedo"]) == "hand_authored_albedo.png"
        assert os.path.basename(m.maps["roughness"]) == "Bricks075A_2K-JPG_Roughness.jpg"


def test_dir_points_at_a_folder_named_differently_from_the_material():
    with tempfile.TemporaryDirectory() as d:
        _make(d, os.path.join("Bricks075A_2K-JPG", "Bricks075A_2K-JPG_Color.jpg"))
        plan = resolve(_cfg(d, {"brick": {"dir": "Bricks075A_2K-JPG"}}))
        assert plan.materials["brick"].maps["albedo"].endswith("Bricks075A_2K-JPG_Color.jpg")


def test_explicit_null_suppresses_a_discovered_map():
    with tempfile.TemporaryDirectory() as d:
        _make(d, *[os.path.join("brick", f) for f in AMBIENTCG])
        plan = resolve(_cfg(d, {"brick": {"maps": {"ao": None}}}))
        assert "ao" not in plan.materials["brick"].maps
        assert "albedo" in plan.materials["brick"].maps


def test_directx_detection_reaches_the_material_spec():
    with tempfile.TemporaryDirectory() as d:
        _make(d, os.path.join("cedar", "Cedar_Color.png"), os.path.join("cedar", "Cedar_NormalDX.png"))
        plan = resolve(_cfg(d, {"cedar": {}}))
        assert plan.materials["cedar"].normal_flip_green is True


def test_normal_flip_green_can_be_forced_in_config():
    with tempfile.TemporaryDirectory() as d:
        _make(d, os.path.join("cedar", "Cedar_NormalGL.png"))
        plan = resolve(_cfg(d, {"cedar": {"normal_flip_green": True}}))
        assert plan.materials["cedar"].normal_flip_green is True


# --- relief -----------------------------------------------------------------

def test_relief_resolves_when_a_height_map_is_present():
    with tempfile.TemporaryDirectory() as d:
        _make(d, *[os.path.join("planks", f) for f in POLYHAVEN])
        plan = resolve(_cfg(d, {"planks": {"relief": {"strength": 0.05, "resolution": 0.02}}}))
        relief = plan.materials["planks"].relief
        assert relief.strength == 0.05 and relief.resolution == 0.02
        assert relief.mid_level == 0.5         # default kept


def test_relief_true_uses_all_defaults():
    with tempfile.TemporaryDirectory() as d:
        _make(d, *[os.path.join("planks", f) for f in POLYHAVEN])
        relief = resolve(_cfg(d, {"planks": {"relief": True}})).materials["planks"].relief
        assert (relief.strength, relief.resolution, relief.mid_level) == (0.03, 0.05, 0.5)


def test_configs_still_setting_the_removed_feather_key_are_accepted():
    # Relief now displaces along the wall axis, so borders no longer need flattening;
    # configs written against the old feathered version must not start failing.
    with tempfile.TemporaryDirectory() as d:
        _make(d, *[os.path.join("planks", f) for f in POLYHAVEN])
        plan = resolve(_cfg(d, {"planks": {"relief": {"strength": 0.05, "feather": 0.06}}}))
        assert plan.materials["planks"].relief.strength == 0.05


def test_relief_without_a_height_map_warns_instead_of_failing():
    with tempfile.TemporaryDirectory() as d:
        _make(d, os.path.join("planks", "planks_diff_4k.jpg"))
        plan = resolve(_cfg(d, {"planks": {"relief": {"strength": 0.05}}}))
        assert plan.materials["planks"].relief is None
        assert any("relief requested but no height" in w for w in plan.warnings)
        assert len(plan.specs) == 1            # the kit still builds, just flat


def test_materials_without_relief_stay_flat():
    with tempfile.TemporaryDirectory() as d:
        _make(d, *[os.path.join("planks", f) for f in POLYHAVEN])
        assert resolve(_cfg(d, {"planks": {}})).materials["planks"].relief is None


def test_unknown_map_role_is_rejected():
    with tempfile.TemporaryDirectory() as d:
        try:
            resolve(_cfg(d, {"brick": {"maps": {"shininess": "x.png"}}}))
        except ValueError as exc:
            assert "shininess" in str(exc)
        else:
            raise AssertionError("expected an unknown-role error")
