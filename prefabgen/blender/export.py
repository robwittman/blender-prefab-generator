"""Output writers. Runs INSIDE Blender.

Each writer takes the current scene (holding exactly one prefab) and a path without
extension. Adding a format is adding one entry here plus the config key.
"""
import bpy

EXTENSIONS = {"blend": ".blend", "glb": ".glb", "fbx": ".fbx"}


def write(fmt: str, path_no_ext: str, pack_textures: bool = True) -> str:
    try:
        writer = _WRITERS[fmt]
    except KeyError:
        raise ValueError(f"unknown output format {fmt!r}; known: {sorted(_WRITERS)}")
    path = path_no_ext + extension_for(fmt, pack_textures)
    writer(path, pack_textures)
    return path


def extension_for(fmt: str, pack_textures: bool = True) -> str:
    """What `write` will actually produce.

    An unpacked glTF is a `.gltf` next to its `.bin` and its images, not a `.glb` — a GLB is a
    single self-contained file by definition, so "GLB with external textures" is not a thing the
    format can express. The caller needs the real extension to record in the manifest.
    """
    if fmt == "glb" and not pack_textures:
        return ".gltf"
    return EXTENSIONS[fmt]


def _blend(path, pack_textures=True):
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=False, copy=True)


<<<<<<< Updated upstream
def _glb(path, pack_textures=True):
    """glTF, packed or not.

    `pack_textures` used to be read only by the `.blend` branch, so every glTF embedded a private
    copy of every texture whatever the config said. With two materials across sixty-eight prefabs
    that is a hundred and thirty-six copies of two texture sets — measured at 1468 MB for a kit
    whose geometry is a few thousand vertices a piece.

    `GLTF_SEPARATE` writes the images beside the model instead. Every prefab in a build exports to
    the same directory and identical image datablocks take identical filenames, so the set lands
    once and every `.gltf` points at it.

    `JPEG` is forced because the exporter's `AUTO` re-encodes anything with an alpha channel — and
    every normal map it touched — as lossless PNG: one 17.7 MB file in a 26.3 MB prefab.
    """
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB" if pack_textures else "GLTF_SEPARATE",
        export_image_format="JPEG",
        export_jpeg_quality=90,
        use_selection=False,
    )


def _fbx(path, pack_textures=True):
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=False,
        apply_unit_scale=True,
        path_mode="COPY" if pack_textures else "RELATIVE",
        embed_textures=pack_textures,
    )
=======
def _glb(path):
    # export_extras defaults to False: without it the pivot contract on the leaf never
    # reaches the engine, and the toolkit has no way to discover how a door opens.
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=False,
                              export_extras=True, export_animations=True)


def _fbx(path):
    bpy.ops.export_scene.fbx(filepath=path, use_selection=False, apply_unit_scale=True,
                             bake_anim=True, use_custom_props=True)
>>>>>>> Stashed changes


_WRITERS = {"blend": _blend, "glb": _glb, "fbx": _fbx}
