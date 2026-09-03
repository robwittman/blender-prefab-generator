"""Real geometric relief displaced from a height map. Runs INSIDE Blender.

A normal map cannot change a silhouette, so a flat wall reads as printed texture at
grazing angles. Displacing actual geometry fixes that, but naive displacement also
pushes the *edges* of the module: vertices on a wall's outer border have 45-degree
blended normals, so they travel sideways off the mating plane. Two neighbouring walls
then overlap where the height map is bright and gap where it is dark, which shows up
as cracks along every join (measured at 12mm of drift on a 2m wall).

The fix is to displace each skin along the wall's own Y axis instead. A border vertex
then moves only in Y, so it stays exactly on the x = +-W/2 and z = 0/H planes however
far it travels: alignment is exact by construction, and the relief runs full-strength
right to the edge. Flattening the border to protect those planes - which is what a
feathered mask does - leaves a flat band at every joint that reads as a ripple across
an assembled wall.
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
    if spec.type not in ("wall", "gable", "corner"):
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
    groups = _relief_groups(obj)

    tex = bpy.data.textures.new(f"relief_{mspec.name}", type="IMAGE")
    tex.image = bpy.data.images.load(path, check_existing=True)
    tex.extension = "REPEAT"

    # One pass per declared face group, each along its OWN axis. A flat wall is two
    # groups on Y; a corner has faces in two axes and declares four.
    for group, axis, sign in groups:
        dsp = obj.modifiers.new(f"Relief_{group}", "DISPLACE")
        dsp.texture = tex
        dsp.texture_coords = "UV"
        dsp.uv_layer = UV_LAYER
        dsp.direction = axis.upper()
        dsp.strength = sign * settings.strength
        dsp.mid_level = settings.mid_level
        dsp.vertex_group = group
        bpy.ops.object.modifier_apply(modifier=dsp.name)

    # The scratch UV layer and mask must not ship inside the prefab.
    # Look both up by name: applying a modifier invalidates existing references.
    obj.data.uv_layers.remove(obj.data.uv_layers[UV_LAYER])
    for group, _axis, _sign in groups:
        obj.vertex_groups.remove(obj.vertex_groups[group])
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


PREFIX = "_relief_"


def _relief_groups(obj):
    """(group, axis, sign) triples describing what may move, and which way.

    A builder that knows its own geometry can declare these itself; anything that does
    not gets the default flat-panel split below.
    """
    declared = [g.name for g in obj.vertex_groups if g.name.startswith(PREFIX)]
    if declared:
        return [(name, name[len(PREFIX):][1], -1.0 if name[len(PREFIX)] == "-" else 1.0)
                for name in sorted(declared)]
    front, back = _skin_groups(obj)
    return [(front, "y", -1.0), (back, "y", 1.0)]


def _skin_groups(obj):
    """Split the mesh into front-skin and back-skin vertices.

    Every vertex sits on one of the two faces (relief only subdivides in x and z), so
    the split is exact. The midpoint comes from the mesh bounds rather than y=0 so it
    holds for every origin mode.
    """
    ys = [v.co.y for v in obj.data.vertices]
    middle = (min(ys) + max(ys)) / 2.0
    front = obj.vertex_groups.new(name="_relief_front")
    back = obj.vertex_groups.new(name="_relief_back")
    front.add([v.index for v in obj.data.vertices if v.co.y < middle], 1.0, "REPLACE")
    back.add([v.index for v in obj.data.vertices if v.co.y >= middle], 1.0, "REPLACE")
    return front.name, back.name


def _warn(report, material, message):
    if report is not None:
        report.setdefault("relief_skipped", []).append({"material": material, "reason": message})
