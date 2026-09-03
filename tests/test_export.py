import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# `prefabgen.blender.export` runs inside Blender and imports `bpy` at module scope. The extension
# logic is ordinary arithmetic about filenames, so it is worth testing outside Blender — a stub is
# what makes that possible, and this is the only thing the module touches at import time.
sys.modules.setdefault("bpy", types.ModuleType("bpy"))

from prefabgen.blender.export import extension_for


def test_packed_gltf_is_a_single_glb():
    assert extension_for("glb", pack_textures=True) == ".glb"


def test_unpacked_gltf_is_a_gltf_beside_its_images():
    # A GLB is a single self-contained file by definition, so unpacking the textures necessarily
    # changes the container. Recording ".glb" in the manifest while writing ".gltf" to disk would
    # give every consumer a path to a file that is not there.
    assert extension_for("glb", pack_textures=False) == ".gltf"


def test_other_formats_do_not_change_container():
    for fmt in ["blend", "fbx"]:
        assert extension_for(fmt, True) == extension_for(fmt, False)


def test_unknown_format_is_refused_rather_than_guessed():
    try:
        extension_for("obj")
    except KeyError:
        return
    raise AssertionError("an unknown format should not resolve to an extension")
