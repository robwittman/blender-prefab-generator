"""Principled BSDF construction from a MaterialSpec. Runs INSIDE Blender.

Mesh UVs are in world metres (see build._uv_project), so tiling is a *material*
property: a Mapping node scales by 1/tile_size. That keeps one mesh valid for any
material and keeps texel density consistent across every size in the matrix.

Missing texture files are a warning, not an error - the material falls back to its
flat base_color so the kit still builds before any art has been dropped in.
"""
import os

import bpy

_COLOR_ROLES = {"albedo"}   # everything else is data, not colour


def build(mspec, report=None):
    """Get or create the Blender material for ``mspec``."""
    existing = bpy.data.materials.get(mspec.name)
    if existing is not None:
        return existing

    mat = bpy.data.materials.new(mspec.name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]

    bsdf.inputs["Base Color"].default_value = tuple(mspec.base_color)
    bsdf.inputs["Roughness"].default_value = mspec.roughness
    bsdf.inputs["Metallic"].default_value = mspec.metallic

    if mspec.kind == "glass":
        # Alpha rather than true transmission: KHR_materials_transmission is patchily
        # supported by engines, while alpha exports as glTF alphaMode BLEND and looks
        # the same in Cycles.
        bsdf.inputs["Alpha"].default_value = mspec.opacity
        for attr, value in (("blend_method", "BLEND"), ("surface_render_method", "BLENDED")):
            try:
                setattr(mat, attr, value)
            except (AttributeError, TypeError):
                pass
        mat.use_backface_culling = False
        return mat

    shader_maps = {r: p for r, p in mspec.maps.items() if r != "height"}
    images = {r: _load(p, report, mspec.name, r) for r, p in shader_maps.items()}
    images = {r: im for r, im in images.items() if im is not None}
    if not images:
        return mat

    coord = nt.nodes.new("ShaderNodeTexCoord")
    coord.location = (-1000, 0)
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.location = (-820, 0)
    scale = 1.0 / mspec.tile_size if mspec.tile_size else 1.0
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])

    for i, (role, image) in enumerate(sorted(images.items())):
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.location = (-620, 300 - i * 300)
        tex.image.colorspace_settings.name = "sRGB" if role in _COLOR_ROLES else "Non-Color"
        nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])

        if role == "albedo":
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        elif role == "roughness":
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Roughness"])
        elif role == "metallic":
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Metallic"])
        elif role == "normal":
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nm.location = (-330, 300 - i * 300)
            nm.inputs["Strength"].default_value = mspec.normal_strength
            source = tex.outputs["Color"]
            if mspec.normal_flip_green:
                source = _flip_green(nt, source, (-470, 300 - i * 300))
            nt.links.new(source, nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        elif role == "ao":
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.location = (-330, 300 - i * 300)
            mix.inputs["Factor"].default_value = 1.0
            albedo_link = bsdf.inputs["Base Color"].links
            if albedo_link:
                nt.links.new(albedo_link[0].from_socket, mix.inputs[6])
            else:
                mix.inputs[6].default_value = tuple(mspec.base_color)
            nt.links.new(tex.outputs["Color"], mix.inputs[7])
            nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    return mat


def _flip_green(nt, source, location):
    """DirectX normal maps store +Y downward; Blender expects OpenGL (+Y up), so the
    green channel has to be inverted or every surface is lit from the wrong side."""
    x, y = location
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    sep.location = (x - 200, y)
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    inv.location = (x - 60, y - 120)
    comb = nt.nodes.new("ShaderNodeCombineColor")
    comb.location = (x + 80, y)
    nt.links.new(source, sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], inv.inputs[1])
    nt.links.new(sep.outputs["Red"], comb.inputs["Red"])
    nt.links.new(inv.outputs["Value"], comb.inputs["Green"])
    nt.links.new(sep.outputs["Blue"], comb.inputs["Blue"])
    return comb.outputs["Color"]


def _load(path, report, mat_name, role):
    if not os.path.exists(path):
        if report is not None:
            report.setdefault("missing_textures", []).append(
                {"material": mat_name, "role": role, "path": path})
        return None
    return bpy.data.images.load(path, check_existing=True)


def relativize(out_dir):
    """Rewrite image paths as blend-relative so the library stays portable."""
    for image in bpy.data.images:
        if image.filepath and not image.packed_file:
            try:
                image.filepath = bpy.path.relpath(image.filepath, start=out_dir)
            except Exception:
                pass


def pack_all():
    for image in bpy.data.images:
        if image.filepath and not image.packed_file:
            try:
                image.pack()
            except Exception:
                pass
