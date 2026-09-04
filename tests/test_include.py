import os
import sys
import tempfile

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prefabgen.config import load, resolve


def _write(root, rel, cfg):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        yaml.safe_dump(cfg, fh)
    return path


SHARED = {
    "pitches": {"shallow": {"rise": 1, "run": 2}, "steep": {"rise": 1, "run": 1}},
    "openings": {"door": {"width": 0.9, "height": 2.1}},
    "output": {"dir": "build", "format": "blend"},
}


# --- merge semantics --------------------------------------------------------

def test_include_pulls_in_the_shared_keys():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "common.yaml", SHARED)
        cfg = load(_write(d, "walls.yaml", {"include": "common.yaml",
                                            "library": {"name": "Walls"}}))
        assert cfg["pitches"]["shallow"] == {"rise": 1, "run": 2}
        assert cfg["openings"]["door"]["width"] == 0.9
        assert cfg["library"] == {"name": "Walls"}
        assert "include" not in cfg


def test_including_file_wins_key_by_key():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "common.yaml", SHARED)
        cfg = load(_write(d, "walls.yaml", {"include": "common.yaml",
                                            "output": {"format": "glb"}}))
        assert cfg["output"] == {"dir": "build", "format": "glb"}   # dir survives


def test_later_includes_win_over_earlier_ones():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "a.yaml", {"defaults": {"thickness": 0.2, "origin": "center"}})
        _write(d, "b.yaml", {"defaults": {"thickness": 0.3}})
        cfg = load(_write(d, "walls.yaml", {"include": ["a.yaml", "b.yaml"]}))
        assert cfg["defaults"] == {"thickness": 0.3, "origin": "center"}


def test_a_list_replaces_rather_than_appends():
    """Predictable over convenient: a config that declares parts owns them outright."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "common.yaml", {"parts": [{"name": "shared"}]})
        cfg = load(_write(d, "walls.yaml", {"include": "common.yaml",
                                            "parts": [{"name": "mine"}]}))
        assert cfg["parts"] == [{"name": "mine"}]


def test_an_include_can_carry_the_parts_list_itself():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "common.yaml", {"parts": [{"name": "shared"}]})
        cfg = load(_write(d, "walls.yaml", {"include": "common.yaml"}))
        assert cfg["parts"] == [{"name": "shared"}]


def test_includes_nest():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "pitches.yaml", {"pitches": {"steep": {"rise": 1, "run": 1}}})
        _write(d, "common.yaml", {"include": "pitches.yaml", "version": 1})
        cfg = load(_write(d, "walls.yaml", {"include": "common.yaml"}))
        assert cfg["pitches"]["steep"] == {"rise": 1, "run": 1} and cfg["version"] == 1


# --- paths ------------------------------------------------------------------

def test_paths_in_an_include_resolve_against_the_included_file():
    """A shared config in its own folder must not have its paths re-based silently."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "shared/common.yaml", {"textures": {"root": "../art"},
                                         "output": {"dir": "../out"}})
        path = _write(d, "kits/walls.yaml", {"include": "../shared/common.yaml"})
        cfg = load(path)
        here = os.path.dirname(path)
        # Both land beside the shared file that named them, not beside walls.yaml.
        assert os.path.normpath(resolve(cfg, base_dir=here).out_dir) == os.path.join(d, "out")
        assert os.path.normpath(os.path.join(here, cfg["textures"]["root"])) == os.path.join(d, "art")


def test_the_root_config_keeps_its_own_paths_untouched():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "common.yaml", {"pitches": {}})
        cfg = load(_write(d, "walls.yaml", {"include": "common.yaml",
                                            "textures": {"root": "../textures"}}))
        assert cfg["textures"]["root"] == "../textures"


def test_an_overriding_path_belongs_to_the_file_that_wrote_it():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "shared/common.yaml", {"textures": {"root": "../art"}})
        cfg = load(_write(d, "kits/walls.yaml", {"include": "../shared/common.yaml",
                                                 "textures": {"root": "own"}}))
        assert cfg["textures"]["root"] == "own"


# --- failures ---------------------------------------------------------------

def test_a_missing_include_names_the_file_that_asked_for_it():
    with tempfile.TemporaryDirectory() as d:
        path = _write(d, "walls.yaml", {"include": "nope.yaml"})
        with pytest.raises(ValueError, match="walls.yaml includes 'nope.yaml'"):
            load(path)


def test_an_include_cycle_is_an_error():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "a.yaml", {"include": "b.yaml"})
        _write(d, "b.yaml", {"include": "a.yaml"})
        with pytest.raises(ValueError, match="include cycle"):
            load(os.path.join(d, "a.yaml"))


def test_a_diamond_is_not_a_cycle():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "base.yaml", {"version": 1})
        _write(d, "a.yaml", {"include": "base.yaml", "defaults": {"thickness": 0.2}})
        _write(d, "b.yaml", {"include": "base.yaml", "defaults": {"origin": "center"}})
        cfg = load(_write(d, "walls.yaml", {"include": ["a.yaml", "b.yaml"]}))
        assert cfg["version"] == 1
        assert cfg["defaults"] == {"thickness": 0.2, "origin": "center"}


def test_include_must_be_a_path_or_a_list_of_paths():
    with tempfile.TemporaryDirectory() as d:
        path = _write(d, "walls.yaml", {"include": {"file": "common.yaml"}})
        with pytest.raises(ValueError, match="must be a path or a list of paths"):
            load(path)


def test_a_config_that_is_not_a_mapping_is_an_error():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "walls.yaml")
        with open(path, "w") as fh:
            fh.write("- one\n- two\n")
        with pytest.raises(ValueError, match="must be a mapping"):
            load(path)


def test_an_empty_include_loads_as_nothing():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "common.yaml"), "w").close()
        cfg = load(_write(d, "walls.yaml", {"include": "common.yaml", "version": 1}))
        assert cfg == {"version": 1}


# --- the shipped example ----------------------------------------------------

def test_the_example_kits_share_one_pitch_library():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "example", "config")
    walls = load(os.path.join(root, "walls.yaml"))
    roofs = load(os.path.join(root, "roofs.yaml"))
    joinery = load(os.path.join(root, "joinery.yaml"))
    assert walls["pitches"] == roofs["pitches"]
    assert walls["openings"] == joinery["openings"]
    assert walls["output"]["manifest"] != roofs["output"]["manifest"]


# --- defaults, scoped by part type ------------------------------------------

WALL = {"type": "wall", "name": "w_{width}x{height}", "matrix": {"width": [2], "height": [2.5]}}
ROOF = {"type": "roof", "piece": "slab", "name": "r_{span}x{run}",
        "matrix": {"span": [2], "run": [2], "pitch": ["steep"]}}
DOOR = {"type": "door", "name": "d_{leaf}", "fits": "door", "matrix": {"leaf": ["braced"]},
        "slots": {"frame": "oak", "leaf": "oak"}}


def _kit(*parts, **top):
    cfg = {"pitches": {"steep": {"rise": 1, "run": 1}},
           "openings": {"door": {"width": 0.9, "height": 2.1}},
           "materials": {"oak": {}}, "parts": list(parts)}
    cfg.update(top)
    return cfg


def _by_type(cfg):
    return {s.type: s for s in resolve(cfg).specs}


def test_a_type_block_beats_the_unqualified_default():
    """The collision: `thickness` is 0.2 to a wall and 0.18 to a roof."""
    specs = _by_type(_kit(WALL, ROOF, defaults={"thickness": 0.2,
                                                "roof": {"thickness": 0.18}}))
    assert specs["wall"].thickness == 0.2
    assert specs["roof"].thickness == 0.18


def test_unqualified_defaults_still_reach_every_part():
    plan = resolve(_kit(WALL, ROOF, defaults={"thickness": 0.3}))
    assert {s.thickness for s in plan.specs} == {0.3}


def test_a_type_block_does_not_leak_into_another_type():
    specs = _by_type(_kit(WALL, ROOF, defaults={"wall": {"thickness": 0.4}}))
    assert specs["wall"].thickness == 0.4
    assert specs["roof"].thickness == 0.18      # untouched, from the code's own default


def test_a_scoped_origin_does_not_reposition_another_type():
    """A flat `origin: bottom_center` would silently move every door off wall_origin."""
    specs = _by_type(_kit(WALL, DOOR, defaults={"wall": {"origin": "min_corner"}}))
    assert specs["wall"].origin == "min_corner"
    assert specs["door"].origin == "wall_origin"


def test_min_border_can_be_scoped_too():
    wall = dict(WALL, name="w_{width}x{height}_{opening}",
                matrix={"width": [2], "height": [2.5], "opening": ["door"]})
    loose = _kit(wall, openings={"door": {"width": 1.5, "height": 2.1}})
    assert resolve(loose).specs and not resolve(loose).skipped
    tight = dict(loose, defaults={"wall": {"min_border": 0.5}})
    assert resolve(tight).skipped and not resolve(tight).specs


def test_a_key_named_for_a_part_type_is_never_read_as_a_value():
    plan = resolve(_kit(ROOF, defaults={"roof": {"thickness": 0.18}}))
    assert plan.specs[0].thickness == 0.18


def test_a_type_block_must_be_a_mapping():
    with pytest.raises(ValueError, match="defaults.roof must be a mapping"):
        resolve(_kit(ROOF, defaults={"roof": 0.18}))


def test_one_shared_defaults_block_serves_a_wall_kit_and_a_roof_kit():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "common.yaml", {"pitches": {"steep": {"rise": 1, "run": 1}},
                                  "defaults": {"min_border": 0.1,
                                               "wall": {"thickness": 0.2},
                                               "roof": {"thickness": 0.18}}})
        walls = load(_write(d, "walls.yaml", {"include": "common.yaml", "parts": [WALL]}))
        roofs = load(_write(d, "roofs.yaml", {"include": "common.yaml", "parts": [ROOF]}))
        assert resolve(walls).specs[0].thickness == 0.2
        assert resolve(roofs).specs[0].thickness == 0.18


def test_a_kit_can_still_override_a_shared_type_block():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "common.yaml", {"defaults": {"wall": {"thickness": 0.2,
                                                        "origin": "bottom_center"}}})
        cfg = load(_write(d, "walls.yaml", {"include": "common.yaml", "parts": [WALL],
                                            "defaults": {"wall": {"thickness": 0.35}}}))
        spec = resolve(cfg).specs[0]
        assert (spec.thickness, spec.origin) == (0.35, "bottom_center")


def test_the_example_kits_share_one_defaults_block():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "example", "config")
    walls = resolve(load(os.path.join(root, "walls.yaml")), base_dir=root)
    roofs = resolve(load(os.path.join(root, "roofs.yaml")), base_dir=root)
    assert {s.thickness for s in walls.specs if s.type == "gable"} == {0.2}
    assert {s.thickness for s in roofs.specs} == {0.18}
