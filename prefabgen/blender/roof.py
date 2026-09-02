"""Procedural roof geometry. Runs INSIDE Blender.

Pieces tile the same plan grid as the walls: a slab's footprint is span x run, and the
sloped panel comes out longer than its run by 1/cos(pitch). Every cut that a
neighbouring piece has to meet is a vertical plane, so slabs butt seamlessly both
side-to-side and up the slope - the same mating-plane discipline the walls use.

Corners are exact rather than approximated: a hip surface is z = min(x, y) * tan(pitch)
and a valley is z = max(x, y) * tan(pitch). Each splits along the diagonal into two
triangles that are individually planar, so the mitre is real geometry, not a fit.
"""
import math

import bmesh
import bpy

from .build import _assign_materials, _uv_project, _vert

SQRT2 = math.sqrt(2.0)


def build(spec, report=None) -> bpy.types.Object:
    if spec.type != "roof":
        raise ValueError(f"no roof builder for part type {spec.type!r}")
    try:
        piece = _PIECES[spec.piece]
    except KeyError:
        raise ValueError(f"unknown roof piece {spec.piece!r}; known: {sorted(_PIECES)}")

    bm = bmesh.new()
    cache: dict = {}
    slots: list = []

    def face(points):
        bm.faces.new([_vert(bm, cache, p) for p in points])
        slots.append(0)

    piece(spec, face)
    _shift(bm, spec)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    _uv_project(bm)

    mesh = bpy.data.meshes.new(spec.name)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(spec.name, mesh)
    _assign_materials(mesh, spec, slots, report)
    obj["prefab_id"] = mesh["prefab_id"] = spec.id
    obj["prefab_category"] = spec.category
    obj["prefab_piece"] = spec.piece
    mesh.update()
    return obj


def _slab(spec, face):
    W, R = spec.span, spec.run
    rise, t = spec.rise, spec.vertical_thickness
    top = [(0.0, 0.0, 0.0), (W, 0.0, 0.0), (W, R, rise), (0.0, R, rise)]
    bot = [(x, y, z - t) for x, y, z in top]
    face(top)
    face(bot)
    for i in range(4):                       # four plumb-cut sides
        j = (i + 1) % 4
        face([top[i], top[j], bot[j], bot[i]])


def _corner(spec, face, pick):
    """pick=min gives a hip (diagonal is the high line); pick=max gives a valley."""
    R = spec.run
    tan, t = math.tan(math.radians(spec.angle)), spec.vertical_thickness
    plan = [(0.0, 0.0), (R, 0.0), (R, R), (0.0, R)]
    top = [(x, y, pick(x, y) * tan) for x, y in plan]
    bot = [(x, y, z - t) for x, y, z in top]
    # Split on the 0-2 diagonal: each half lies exactly in one roof plane.
    face([top[0], top[1], top[2]])
    face([top[0], top[2], top[3]])
    face([bot[0], bot[1], bot[2]])
    face([bot[0], bot[2], bot[3]])
    for i in range(4):
        j = (i + 1) % 4
        face([top[i], top[j], bot[j], bot[i]])


def _ridge(spec, face):
    """A tent capping the apex; its opening angle follows the pitch."""
    W = spec.span
    w = spec.cap_width / 2.0
    tan = math.tan(math.radians(spec.angle))
    t = spec.cap_thickness / math.cos(math.radians(spec.angle))
    drop = w * tan
    _extrude(face, _cap_profile(w, drop, t), lambda s, p, z: (s, p, z), 0.0, W)


def _cap(spec, face, sign):
    """Trim swept along a hip or valley line.

    The line climbs at atan(tan(pitch)/sqrt(2)) because it runs diagonally across the
    footprint, and the surface falls away sideways at that same effective angle - so
    the trim sits flush on the mitre instead of hovering over it.
    """
    R = spec.run
    tan = math.tan(math.radians(spec.angle))
    tan_hip = tan / SQRT2
    w = spec.cap_width / 2.0
    t = spec.cap_thickness / math.cos(math.radians(spec.angle))
    profile = _cap_profile(w, sign * w * tan_hip, t)

    def place(s, p, z):
        return (s / SQRT2 + p / SQRT2, s / SQRT2 - p / SQRT2, s * tan_hip + z)

    _extrude(face, profile, place, 0.0, R * SQRT2)


def _cap_profile(w, drop, t):
    """Cross-section of a trim cap, as (offset, height) pairs.

    The *inner* surface is the one that lies on the roof plane and the outer sits ``t``
    proud of it. Building it the other way round buries the cap in the slab it is meant
    to sit on, which renders as a z-fighting slot rather than a raised ridge.
    """
    return [(-w, -drop + t), (0.0, t), (w, -drop + t),
            (w, -drop), (0.0, 0.0), (-w, -drop)]


def _extrude(face, profile, place, start, end):
    """Sweep a closed cross-section between two stations."""
    a = [place(start, p, z) for p, z in profile]
    b = [place(end, p, z) for p, z in profile]
    face(a)
    face(list(reversed(b)))
    for i in range(len(profile)):
        j = (i + 1) % len(profile)
        face([a[i], a[j], b[j], b[i]])


def _shift(bm, spec):
    """Centre the footprint so pieces snap on the same grid as the walls."""
    if spec.origin != "footprint_center":
        raise ValueError(f"unknown roof origin mode {spec.origin!r}")
    if spec.piece == "slab":
        dx, dy = -spec.span / 2.0, -spec.run / 2.0
    elif spec.piece == "ridge":
        dx, dy = -spec.span / 2.0, 0.0
    else:
        dx, dy = -spec.run / 2.0, -spec.run / 2.0
    for v in bm.verts:
        v.co.x += dx
        v.co.y += dy


_PIECES = {
    "slab": _slab,
    "ridge": _ridge,
    "hip": lambda s, f: _corner(s, f, min),
    "valley": lambda s, f: _corner(s, f, max),
    "hip_cap": lambda s, f: _cap(s, f, 1.0),
    "valley_cap": lambda s, f: _cap(s, f, -1.0),
}
