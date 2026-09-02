"""Output writers. Runs INSIDE Blender.

Each writer takes the current scene (holding exactly one prefab) and a path without
extension. Adding a format is adding one entry here plus the config key.
"""
import bpy

EXTENSIONS = {"blend": ".blend", "glb": ".glb", "fbx": ".fbx"}


def write(fmt: str, path_no_ext: str) -> str:
    try:
        writer = _WRITERS[fmt]
    except KeyError:
        raise ValueError(f"unknown output format {fmt!r}; known: {sorted(_WRITERS)}")
    path = path_no_ext + EXTENSIONS[fmt]
    writer(path)
    return path


def _blend(path):
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=False, copy=True)


def _glb(path):
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=False)


def _fbx(path):
    bpy.ops.export_scene.fbx(filepath=path, use_selection=False, apply_unit_scale=True)


_WRITERS = {"blend": _blend, "glb": _glb, "fbx": _fbx}
