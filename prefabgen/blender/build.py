"""Procedural wall geometry. Runs INSIDE Blender (needs bpy/bmesh).

A wall lives in local space as x in [0, W], z in [0, H], y in [-T/2, +T/2], then gets
shifted according to the spec's origin mode. Openings are not booleaned: the front and
back faces are decomposed into a grid whose cut lines come from the opening rectangles,
and cells that land inside an opening are simply not emitted. That keeps every face a
clean quad and makes the output deterministic.
"""
import math

import bmesh
import bpy

from . import materials as materials_mod

EPS = 1e-6


def build(spec, report=None) -> bpy.types.Object:
    if spec.type != "wall":
        raise ValueError(f"no builder for part type {spec.type!r}")

    bm = bmesh.new()
    cache: dict = {}
    slots: list[int] = []          # material slot per face, in creation order

    W, H, T = spec.width, spec.height, spec.thickness
    y0, y1 = -T / 2.0, T / 2.0
    rects = [o.bounds(W) for o in spec.openings]

    xs = _cuts([0.0, W] + [v for r in rects for v in r[:2]], 0.0, W)
    zs = _cuts([0.0, H] + [v for r in rects for v in r[2:]], 0.0, H)

    # Relief samples a height map per vertex, so the grid must be laid down at a fixed
    # world resolution here. Subdividing the finished mesh instead gives every face the
    # same cut count regardless of its size, which samples a 4m wall ten times coarser
    # than a 1m one and turns the same material into different depths across the kit.
    relief = spec.material.relief
    if relief:
        xs = _densify(xs, relief.resolution)
        zs = _densify(zs, relief.resolution)

    solid = [[not _in_any(rects, (xs[i] + xs[i + 1]) / 2.0, (zs[j] + zs[j + 1]) / 2.0)
              for j in range(len(zs) - 1)] for i in range(len(xs) - 1)]

    def face(points, slot=0):
        verts = [_vert(bm, cache, p) for p in points]
        bm.faces.new(verts)
        slots.append(slot)

    # Front (-Y) and back (+Y) skins.
    for i in range(len(xs) - 1):
        for j in range(len(zs) - 1):
            if not solid[i][j]:
                continue
            a, b, c, d = xs[i], xs[i + 1], zs[j], zs[j + 1]
            face([(a, y0, c), (b, y0, c), (b, y0, d), (a, y0, d)])
            face([(a, y1, c), (b, y1, c), (b, y1, d), (a, y1, d)])

    # Outer edges, segmented so a floor-level doorway leaves a real gap.
    for i in range(len(xs) - 1):
        a, b = xs[i], xs[i + 1]
        if solid[i][0]:
            face([(a, y0, 0.0), (b, y0, 0.0), (b, y1, 0.0), (a, y1, 0.0)])
        if solid[i][-1]:
            face([(a, y0, H), (b, y0, H), (b, y1, H), (a, y1, H)])
    for j in range(len(zs) - 1):
        c, d = zs[j], zs[j + 1]
        if solid[0][j]:
            face([(0.0, y0, c), (0.0, y1, c), (0.0, y1, d), (0.0, y0, d)])
        if solid[-1][j]:
            face([(W, y0, c), (W, y1, c), (W, y1, d), (W, y0, d)])

    # Reveals: the inner surfaces of each opening.
    reveal_slot = 1 if spec.reveal_material else 0
    for (x0, x1, z0, z1) in rects:
        if z0 > EPS:
            face([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], reveal_slot)
        if z1 < H - EPS:
            face([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], reveal_slot)
        if x0 > EPS:
            face([(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)], reveal_slot)
        if x1 < W - EPS:
            face([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], reveal_slot)

    _shift(bm, spec)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    _uv_project(bm)   # world metres; per-material tiling happens in the shader

    mesh = bpy.data.meshes.new(spec.name)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(spec.name, mesh)
    _assign_materials(mesh, spec, slots, report)
    # Stable identity travels with the asset, so a creator's level keeps resolving
    # even if the display name or filename changes later.
    obj["prefab_id"] = mesh["prefab_id"] = spec.id
    obj["prefab_category"] = spec.category
    mesh.update()
    return obj


def _cuts(values, lo, hi):
    """Sorted unique cut lines, clamped to [lo, hi], collapsing near-duplicates."""
    out = []
    for v in sorted(min(max(v, lo), hi) for v in values):
        if not out or v - out[-1] > EPS:
            out.append(v)
    return out


def _densify(cuts, target):
    """Insert cuts so no span exceeds ``target`` metres, keeping the existing ones."""
    if target <= 0:
        return cuts
    out = []
    for lo, hi in zip(cuts, cuts[1:]):
        steps = max(1, int(math.ceil((hi - lo) / target - 1e-9)))
        out.extend(lo + (hi - lo) * i / steps for i in range(steps))
    out.append(cuts[-1])
    return out


def _in_any(rects, x, z):
    return any(x0 < x < x1 and z0 < z < z1 for (x0, x1, z0, z1) in rects)


def _vert(bm, cache, p):
    key = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
    v = cache.get(key)
    if v is None:
        v = cache[key] = bm.verts.new(key)
    return v


def _shift(bm, spec):
    if spec.origin == "bottom_center":
        dx, dy, dz = -spec.width / 2.0, 0.0, 0.0
    elif spec.origin == "center":
        dx, dy, dz = -spec.width / 2.0, 0.0, -spec.height / 2.0
    elif spec.origin == "min_corner":
        dx, dy, dz = 0.0, spec.thickness / 2.0, 0.0
    else:
        raise ValueError(f"unknown origin mode {spec.origin!r}")
    if (dx, dy, dz) != (0.0, 0.0, 0.0):
        for v in bm.verts:
            v.co.x += dx
            v.co.y += dy
            v.co.z += dz


def _uv_project(bm, scale=1.0):
    """World-scale planar projection per face, so texel density matches across variants."""
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        n = f.normal
        ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
        for loop in f.loops:
            co = loop.vert.co
            if ax >= ay and ax >= az:
                u, v = co.y, co.z
            elif ay >= ax and ay >= az:
                u, v = co.x, co.z
            else:
                u, v = co.x, co.y
            loop[uv].uv = (u * scale, v * scale)


def _assign_materials(mesh, spec, slots, report=None):
    specs = [spec.material]
    if getattr(spec, "reveal_material", None) and 1 in slots:   # skip the empty slot on solid walls
        specs.append(spec.reveal_material)
    for mspec in specs:
        mesh.materials.append(materials_mod.build(mspec, report))
    for poly, slot in zip(mesh.polygons, slots):
        poly.material_index = min(slot, len(specs) - 1)
