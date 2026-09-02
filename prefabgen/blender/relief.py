"""Real geometric relief displaced from a height map. Runs INSIDE Blender.

A normal map cannot change a silhouette, so a flat wall reads as printed texture at
grazing angles. Displacing actual geometry fixes that, but naive displacement also
pushes the *edges* of the module: vertices on a wall's outer border have 45-degree
blended normals, so they travel sideways off the mating plane. Two neighbouring walls
then overlap where the height map is bright and gap where it is dark, which shows up
as cracks along every join (measured at 12mm of drift on a 2m wall).

The fix is a vertex-group mask that ramps displacement to zero over ``feather`` metres
at every surface a neighbour touches - the left/right mating planes, the floor and
ceiling planes, and the opening reveals. Border vertices then do not move at all, so
alignment is exact by construction rather than by luck, at the cost of the relief
flattening out in that border band.
"""
import os

import bpy

UV_LAYER = "_relief_uv"


def apply(obj, spec, report=None):
    """Displace ``obj`` in place. Returns a stats dict, or None if nothing was done."""
    mspec = spec.material
    settings = mspec.relief
    if not settings:
        return None
    if spec.type != "wall":
        _warn(report, mspec.name, f"relief is not implemented for {spec.type} parts yet; "
                                  f"{spec.name} stays flat")
        return None
    path = mspec.maps.get("height")
    if not path or not os.path.exists(path):
        _warn(report, mspec.name, f"no height map at {path!r}")
        return None

    # build.py already laid the grid down at settings.resolution, so there is nothing
    # to subdivide here - and nothing that would sample unevenly across the library.
    before = len(obj.data.vertices)
    bpy.context.view_layer.objects.active = obj

    _scaled_uvs(obj.data, mspec.tile_size)
    group_name = _mask(obj, spec, settings.feather).name

    tex = bpy.data.textures.new(f"relief_{mspec.name}", type="IMAGE")
    tex.image = bpy.data.images.load(path, check_existing=True)
    tex.extension = "REPEAT"

    dsp = obj.modifiers.new("Relief", "DISPLACE")
    dsp.texture = tex
    dsp.texture_coords = "UV"
    dsp.uv_layer = UV_LAYER
    dsp.direction = "NORMAL"
    dsp.strength = settings.strength
    dsp.mid_level = settings.mid_level
    dsp.vertex_group = group_name
    bpy.ops.object.modifier_apply(modifier=dsp.name)

    # The scratch UV layer and mask must not ship inside the prefab.
    # Look both up by name: applying a modifier invalidates existing references.
    obj.data.uv_layers.remove(obj.data.uv_layers[UV_LAYER])
    obj.vertex_groups.remove(obj.vertex_groups[group_name])
    # The height map is consumed at build time; keep it out of the saved file.
    if tex.image.users <= 1:
        bpy.data.images.remove(tex.image)
    bpy.data.textures.remove(tex)

    obj.data.update()
    return {"vertices": len(obj.data.vertices), "strength": settings.strength,
            "resolution": settings.resolution}


def _scaled_uvs(mesh, tile_size):
    """Mesh UVs are world metres and the shader tiles by 1/tile_size; the Displace
    modifier reads UVs raw, so it needs its own pre-scaled copy to stay in register
    with the albedo and normal maps."""
    base = mesh.uv_layers.active
    scaled = mesh.uv_layers.new(name=UV_LAYER, do_init=True)
    inv = 1.0 / tile_size if tile_size else 1.0
    for i, loop in enumerate(base.data):
        scaled.data[i].uv = (loop.uv[0] * inv, loop.uv[1] * inv)
    mesh.uv_layers.active = base
    base.active_render = True
    return scaled


def _mask(obj, spec, feather):
    group = obj.vertex_groups.new(name="_relief_mask")
    W, H = spec.width, spec.height
    rects = [o.bounds(W) for o in spec.openings]
    for vert in obj.data.vertices:
        x, z = _to_wall_local(vert.co, spec)
        distance = min(x, W - x, z, H - z)
        for rect in rects:
            distance = min(distance, _distance_to_rect(x, z, rect))
        weight = 0.0 if feather <= 0 else max(0.0, min(1.0, distance / feather))
        group.add([vert.index], weight, "REPLACE")
    return group


def _to_wall_local(co, spec):
    """Undo the origin shift applied in build._shift, giving x in [0, W], z in [0, H]."""
    if spec.origin == "bottom_center":
        return co.x + spec.width / 2.0, co.z
    if spec.origin == "center":
        return co.x + spec.width / 2.0, co.z + spec.height / 2.0
    if spec.origin == "min_corner":
        return co.x, co.z
    raise ValueError(f"unknown origin mode {spec.origin!r}")


def _distance_to_rect(x, z, rect):
    """Distance from (x, z) to an opening's border; zero on or inside it."""
    x0, x1, z0, z1 = rect
    dx = max(x0 - x, 0.0, x - x1)
    dz = max(z0 - z, 0.0, z - z1)
    if dx == 0.0 and dz == 0.0:
        return 0.0
    return (dx * dx + dz * dz) ** 0.5


def _warn(report, material, message):
    if report is not None:
        report.setdefault("relief_skipped", []).append({"material": material, "reason": message})
