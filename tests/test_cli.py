"""The read-only commands. `build` and `showcase` shell out to Blender, but `textures`
and `plan` are pure reporting - and a stale attribute in one of them crashes the
command outright, which is exactly the kind of break unit tests should catch."""
import os
import sys
import types

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prefabgen import cli

POLYHAVEN = ["planks_diff_4k.jpg", "planks_nor_gl_4k.jpg", "planks_rough_4k.jpg",
             "planks_ao_4k.jpg", "planks_disp_4k.jpg"]


def _kit(tmp_path, materials):
    """A one-wall config on disk, with texture files beside it."""
    for name, files in materials.items():
        folder = tmp_path / "textures" / name
        folder.mkdir(parents=True, exist_ok=True)
        for f in files:
            (folder / f).write_bytes(b"")
    cfg = {
        "output": {"dir": "build"},
        "textures": {"root": "textures"},
        "materials": {name: ({"relief": {"strength": 0.05}} if "disp" in " ".join(files)
                             else {}) for name, files in materials.items()},
        "parts": [{"type": "wall", "name": "wall_{width}x{height}_{material}",
                   "matrix": {"width": [2], "height": [2.5],
                              "material": sorted(materials)}}],
    }
    path = tmp_path / "kit.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return types.SimpleNamespace(config=str(path), filter=None)


def test_textures_reports_a_relief_material(tmp_path, capsys):
    args = _kit(tmp_path, {"planks": POLYHAVEN})
    assert cli.cmd_textures(args) == 0
    out = capsys.readouterr().out
    assert "relief:" in out and "strength 0.05m" in out
    assert "planks_disp_4k.jpg" in out


def test_textures_reports_a_material_with_nothing_found(tmp_path, capsys):
    args = _kit(tmp_path, {"plaster": []})
    assert cli.cmd_textures(args) == 0
    assert "nothing found" in capsys.readouterr().out


def test_plan_lists_every_prefab_and_counts_them(tmp_path, capsys):
    args = _kit(tmp_path, {"planks": POLYHAVEN, "plaster": []})
    assert cli.cmd_plan(args) == 0
    out = capsys.readouterr().out                      # plan prints ids, not names
    assert "wall.2500.planks.2000" in out and "wall.2500.plaster.2000" in out
    assert "2 prefab(s)" in out


def test_a_filter_narrows_the_plan(tmp_path, capsys):
    args = _kit(tmp_path, {"planks": POLYHAVEN, "plaster": []})
    args.filter = "*_plaster"                          # a glob over the name...
    assert cli.cmd_plan(args) == 0
    out = capsys.readouterr().out                      # ...still prints the id
    assert "wall.2500.plaster.2000" in out and "planks" not in out
    assert "1 prefab(s)" in out
