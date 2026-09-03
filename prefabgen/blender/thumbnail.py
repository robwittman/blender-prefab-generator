"""Asset-picker preview renders. Runs INSIDE Blender.

Cycles rather than EEVEE: EEVEE needs a GL context that headless Blender does not
reliably have, whereas Cycles renders identically on any machine and CI box. Each
prefab is framed to fill its own thumbnail, which is what an icon grid wants; the
dimensions are in the manifest for anything that needs true relative scale.
"""
import math

import bpy
from mathutils import Matrix, Vector

# Camera looks down this direction (world space), giving a three-quarter view.
VIEW_DIR = Vector((-1.0, 1.0, -0.55)).normalized()
MARGIN = 1.25


def setup(size=512, samples=48):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    try:
        scene.cycles.device = "CPU"
    except Exception:
        pass
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True   # composites onto any picker background

    world = bpy.data.worlds.new("ThumbWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.05, 0.055, 0.06, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    scene.world = world

    cam_data = bpy.data.cameras.new("ThumbCam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("ThumbCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    _light("Key", (4, -6, 6), 5.0, 900)
    _light("Fill", (-6, -3, 2), 3.0, 200)
    _light("Rim", (0, 6, 4), 3.0, 260)
    return cam


def _light(name, location, size, power):
    data = bpy.data.lights.new(name, type="AREA")
    data.size = size
    data.energy = power
    obj = bpy.data.objects.new(name, data)
    obj.location = location
    obj.rotation_euler = _look_at(Vector(location), Vector((0, 0, 0)))
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _look_at(eye, target):
    return (target - eye).to_track_quat("-Z", "Y").to_euler()


def frame(cam, target):
    """Point the ortho camera at ``target`` (an object or a hierarchy) and fit it."""
    objects = list(target) if isinstance(target, (list, tuple)) else [target]
    meshes = [o for o in objects if o.type == "MESH"] or objects
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    centre = sum(corners, Vector()) / len(corners)
    radius = max((c - centre).length for c in corners) or 1.0

    # Build the camera matrix by hand and assign it, rather than setting location and
    # rotation and reading matrix_world back: that is evaluated lazily, so the fit
    # below would silently be computed against a stale (identity) matrix.
    location = centre - VIEW_DIR * (radius * 4.0)
    rotation = (centre - location).to_track_quat("-Z", "Y").to_matrix().to_4x4()
    matrix = Matrix.Translation(location) @ rotation
    cam.matrix_world = matrix

    local = [matrix.inverted() @ c for c in corners]
    extent_x = max(abs(v.x) for v in local)
    extent_y = max(abs(v.y) for v in local)
    cam.data.ortho_scale = 2.0 * max(extent_x, extent_y) * MARGIN


def render(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path
