"""Gallery and sample-building renders. Runs INSIDE Blender.

Pieces are rebuilt from their specs rather than loaded from the shipped .blend files,
so the showcase always reflects the current builders and picks up relief automatically.

The gallery lays every piece out on one ground plane at true relative scale. That is
the point of it: per-prefab thumbnails are each framed to fit, so a 1m wall and a 4m
wall look identical there, which is exactly the mistake a modular kit cannot afford to
let a playtester make.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

from prefabgen.blender import build as build_mod
from prefabgen.blender import relief as relief_mod
from prefabgen.blender import roof as roof_mod
from prefabgen.spec import spec_from_dict

VIEW = Vector((-0.62, 0.92, -0.78)).normalized()


# --- scene ------------------------------------------------------------------

def scene(samples=96):
    # read_factory_settings wipes every datablock, so any cached reference from a
    # previous render in this process is now dangling. Drop it, or the next label()
    # raises "StructRNA of type Material has been removed" and the second image of a
    # two-image run never happens.
    global _LABEL_MAT
    _LABEL_MAT = None
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    try:
        sc.cycles.device = "CPU"
    except Exception:
        pass
    sc.unit_settings.system = "METRIC"
    sc.render.image_settings.file_format = "PNG"

    world = bpy.data.worlds.new("Showcase")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.83, 0.85, 0.88, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.1
    sc.world = world

    _light("Key", (28, -34, 40), 30, 9000)
    _light("Fill", (-30, -18, 16), 26, 2600)
    _light("Rim", (6, 34, 22), 22, 3000)
    return sc


def ground(size, centre=(0, 0)):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(centre[0], centre[1], -0.001))
    plane = bpy.context.object
    mat = bpy.data.materials.new("Ground")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.62, 0.63, 0.65, 1)
    bsdf.inputs["Roughness"].default_value = 0.95
    plane.data.materials.append(mat)
    return plane


def _light(name, location, size, power):
    data = bpy.data.lights.new(name, type="AREA")
    data.size, data.energy = size, power
    obj = bpy.data.objects.new(name, data)
    obj.location = location
    obj.rotation_euler = (Vector((0, 0, 0)) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(obj)


# --- pieces -----------------------------------------------------------------

def make(spec, report=None):
    builder = roof_mod.build if spec.type == "roof" else build_mod.build
    obj = builder(spec, report)
    bpy.context.collection.objects.link(obj)
    relief_mod.apply(obj, spec, report)
    return obj


def bounds(obj):
    cs = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return (Vector((min(c.x for c in cs), min(c.y for c in cs), min(c.z for c in cs))),
            Vector((max(c.x for c in cs), max(c.y for c in cs), max(c.z for c in cs))))


def sit_at(obj, x, y, z=0.0):
    """Centre the piece's footprint on (x, y) and rest it on z."""
    lo, hi = bounds(obj)
    mid = (lo + hi) / 2.0
    obj.location = Vector((x - mid.x, y - mid.y, z - lo.z))
    bpy.context.view_layer.update()
    return obj


def place(obj, x, y, z=0.0, rot_z=0.0):
    """Place by the piece's own origin, which is the grid-snapping point."""
    obj.location = Vector((x, y, z))
    obj.rotation_euler = (0.0, 0.0, rot_z)
    bpy.context.view_layer.update()
    return obj


# --- labels -----------------------------------------------------------------

_LABEL_MAT = None


def label(text, location, size, rotation):
    global _LABEL_MAT
    if _LABEL_MAT is None:
        _LABEL_MAT = bpy.data.materials.new("Label")
        _LABEL_MAT.use_nodes = True
        bsdf = _LABEL_MAT.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (0.05, 0.06, 0.08, 1)
        bsdf.inputs["Roughness"].default_value = 1.0
    curve = bpy.data.curves.new(name="label", type="FONT")
    curve.body = text
    curve.align_x = "CENTER"
    curve.align_y = "TOP"
    curve.size = size
    obj = bpy.data.objects.new("label", curve)
    obj.location = location
    obj.rotation_euler = rotation          # billboard: match the camera exactly
    obj.data.materials.append(_LABEL_MAT)
    bpy.context.collection.objects.link(obj)
    return obj


def short_label(spec):
    if spec.type == "roof":
        size = f"{_n(spec.span)}x{_n(spec.run)}" if spec.piece == "slab" else _n(spec.run)
        return f"{spec.piece} {size} {spec.pitch}\n{spec.material.name}"
    kinds = ", ".join(o.kind for o in spec.openings) or "solid"
    return f"{_n(spec.width)}x{_n(spec.height)} {kinds}\n{spec.material.name}"


def _n(v):
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


# --- camera -----------------------------------------------------------------

def aim(targets, centre, pad=1.06, aspect=1.0):
    """Frame ``targets`` tightly.

    Sizing from max |x| / |y| about the view axis (the obvious way) charges for the
    content's *offset* from that axis as well as its size, so anything not perfectly
    centred is framed at up to twice the scale it needs. Measure the real min/max in
    camera space, slide the camera onto that midpoint, then size from the span.
    """
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    world = [Vector(c) for t in targets for c in _corners(t)]
    radius = max((p - centre).length for p in world) or 1.0
    loc = centre - VIEW * (radius * 4.0)
    rot = (centre - loc).to_track_quat("-Z", "Y").to_matrix().to_4x4()
    cam.matrix_world = Matrix.Translation(loc) @ rot

    pts = [cam.matrix_world.inverted() @ p for p in world]
    lo_x, hi_x = min(p.x for p in pts), max(p.x for p in pts)
    lo_y, hi_y = min(p.y for p in pts), max(p.y for p in pts)

    basis = cam.matrix_world.to_3x3()
    cam.location = (loc + basis @ Vector((1, 0, 0)) * ((lo_x + hi_x) / 2)
                        + basis @ Vector((0, 1, 0)) * ((lo_y + hi_y) / 2))

    ex, ey = (hi_x - lo_x) / 2, (hi_y - lo_y) / 2
    cam.data.ortho_scale = 2.0 * max(ex, ey * aspect) * pad
    bpy.context.view_layer.update()
    return cam


def _corners(obj):
    return [obj.matrix_world @ Vector(c) for c in obj.bound_box]


def render(path, width, height):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = width, height
    sc.render.resolution_percentage = 100
    sc.render.filepath = path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.render.render(write_still=True)
    return path
