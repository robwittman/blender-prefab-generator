"""Door and window geometry. Runs INSIDE Blender.

Joinery is built to fill a *named opening* that the wall config also cuts, so the hole
and the thing filling it come from one definition and cannot drift apart. Dimensions
here are all derived from that opening plus the frame profile - nothing is restated.

Doors are the first prefab type that is not a single mesh: they emit a root with a
static ``frame`` child and a ``leaf`` child whose origin sits exactly on the hinge
axis. That origin is the real deliverable - it is what lets any engine swing the door,
whether it plays the baked clip or drives the node itself.
"""
import math

import bmesh
import bpy

from .build import _uv_project, _vert
from . import materials as materials_mod

SLOT_ORDER = ("frame", "leaf", "glass", "hardware")
PATTERNS = {"single": (1, 1), "cross": (2, 2), "grid": (3, 2)}


class _Part:
    """Accumulates boxes tagged with a material slot name."""

    def __init__(self):
        self.bm = bmesh.new()
        self.cache = {}
        self.slots = []

    def face(self, points, slot):
        self.bm.faces.new([_vert(self.bm, self.cache, p) for p in points])
        self.slots.append(slot)

    def plate(self, u0, u1, v0, v1, y0, y1, slot):
        """Box in leaf-local terms: u across the leaf, v up it, y through it."""
        self.box(u0, u1, y0, y1, v0, v1, slot)

    def mirror_x(self):
        """Flip a left-hung leaf into a right-hung one. Everything is authored once
        around the hinge at u=0; mirroring about it keeps the hinge exactly in place."""
        for v in self.bm.verts:
            v.co.x = -v.co.x

    def box(self, x0, x1, y0, y1, z0, z1, slot):
        if x1 - x0 < 1e-6 or y1 - y0 < 1e-6 or z1 - z0 < 1e-6:
            return
        v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        for a, b, c, d in [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
                           (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
            self.face([v[a], v[b], v[c], v[d]], slot)

    def finish(self, name, spec, report):
        bm = self.bm
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        _uv_project(bm)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()

        used = [s for s in SLOT_ORDER if s in self.slots]
        index = {s: i for i, s in enumerate(used)}
        for mspec in (spec.slots[s] for s in used):
            mesh.materials.append(materials_mod.build(mspec, report))
        for poly, slot in zip(mesh.polygons, self.slots):
            poly.material_index = index[slot]
        mesh.update()
        return bpy.data.objects.new(name, mesh)


def build(spec, report=None) -> bpy.types.Object:
    if spec.type == "window":
        obj = _window(spec, report)
        _tag(obj, spec)
        return obj
    if spec.type != "door":
        raise ValueError(f"no joinery builder for {spec.type!r}")

    root = bpy.data.objects.new(spec.name, None)
    _tag(root, spec)
    frame = _door_frame(spec, report)
    frame.parent = root
    leaf = _door_leaf(spec, report)
    leaf.parent = root
    _bake_hinge(leaf, spec)
    return root


def _tag(obj, spec):
    obj["prefab_id"] = spec.id
    obj["prefab_category"] = spec.category
    obj["prefab_fits"] = spec.fits          # lets a picker filter to what fits a hole


# --- shared frame pieces ----------------------------------------------------

def _bounds(spec):
    o, f = spec.opening, spec.frame
    x0 = o.offset - o.width / 2.0
    x1 = o.offset + o.width / 2.0
    return x0, x1, o.sill, o.sill + o.height, spec.wall_thickness / 2.0, f


def _lining(part, spec, sill_board):
    x0, x1, z0, z1, ht, f = _bounds(spec)
    L = f.lining
    part.box(x0, x0 + L, -ht, ht, z0, z1, "frame")           # jambs run the full height
    part.box(x1 - L, x1, -ht, ht, z0, z1, "frame")
    part.box(x0 + L, x1 - L, -ht, ht, z1 - L, z1, "frame")   # head
    if sill_board:
        part.box(x0 + L, x1 - L, -ht, ht, z0, z0 + L, "frame")


def _casing(part, spec, wrap_sill):
    """Flat casing standing proud of both wall faces, framing the opening."""
    x0, x1, z0, z1, ht, f = _bounds(spec)
    C, D = f.casing, f.casing_depth
    if C <= 0 or D <= 0:
        return
    top = z1 + C
    bottom = z0 - C if wrap_sill else z0
    for y0, y1 in ((-ht - D, -ht), (ht, ht + D)):
        part.box(x0 - C, x0, y0, y1, bottom, top, "frame")
        part.box(x1, x1 + C, y0, y1, bottom, top, "frame")
        part.box(x0, x1, y0, y1, z1, top, "frame")
        if wrap_sill:
            part.box(x0, x1, y0, y1, bottom, z0, "frame")


# --- doors ------------------------------------------------------------------

def _door_frame(spec, report):
    part = _Part()
    _lining(part, spec, sill_board=False)
    _casing(part, spec, wrap_sill=False)
    return part.finish("frame", spec, report)


def _leaf_rect(spec):
    """Leaf size and the world position of its hinge axis."""
    x0, x1, z0, z1, ht, f = _bounds(spec)
    L, c = f.lining, f.clearance
    lw = spec.clear_width - 2 * c
    lh = spec.clear_height - 2 * c
    back = -ht + f.rebate + spec.leaf_thickness      # hinge knuckle on the swing side
    hinge_x = (x0 + L + c) if spec.hinge == "left" else (x1 - L - c)
    return lw, lh, hinge_x, back, z0 + c


def _door_leaf(spec, report):
    part = _Part()
    lw, lh, hinge_x, hinge_y, hinge_z = _leaf_rect(spec)
    t = spec.leaf_thickness

    # Authored in a canonical frame: u runs from the hinge at 0 out to lw, v up the
    # leaf, y through it with the front face at -t.
    styles = {"braced": _braced_leaf, "banded": _banded_leaf}
    try:
        styles[spec.leaf](part, lw, lh, t)
    except KeyError:
        raise ValueError(f"unknown leaf style {spec.leaf!r}; known: {sorted(styles)}")
    _ring_pull(part, lw, lh, t)

    if spec.hinge == "right":
        part.mirror_x()
    obj = part.finish("leaf", spec, report)
    # Geometry is authored around the hinge; the object then sits ON the hinge axis, so
    # rotating it swings the leaf correctly with no offset baked into the mesh.
    obj.location = (hinge_x, hinge_y, hinge_z)
    return obj


def _boards(part, lw, lh, y_front, y_back, slot="leaf"):
    """Vertical boards with chamfered edges, so the joins read as V-grooves.

    Widths vary deterministically: equal boards with hairline gaps look machine-milled,
    which was most of what made the first pass read as a modern flush door.
    """
    count = max(3, int(round(lw / 0.185)))
    weights = [1.0 + 0.17 * math.sin((i + 1) * 2.3999632) for i in range(count)]
    total = sum(weights)
    chamfer = 0.007
    u = 0.0
    for w in weights:
        width = lw * w / total
        _chamfered_board(part, u, u + width, 0.0, lh, y_front, y_back, chamfer, slot)
        u += width


def _chamfered_board(part, u0, u1, v0, v1, y_front, y_back, c, slot):
    b = [(u0, y_back, v0), (u1, y_back, v0), (u1, y_back, v1), (u0, y_back, v1)]
    f = [(u0 + c, y_front, v0), (u1 - c, y_front, v0),
         (u1 - c, y_front, v1), (u0 + c, y_front, v1)]
    part.face(f, slot)                                    # front
    part.face(list(reversed(b)), slot)                    # back
    part.face([b[0], f[0], f[3], b[3]], slot)             # chamfered edges
    part.face([b[1], b[2], f[2], f[1]], slot)
    part.face([b[0], b[1], f[1], f[0]], slot)             # bottom
    part.face([b[3], f[3], f[2], b[2]], slot)             # top


def _diagonal(part, u0, v0, u1, v1, width, y0, y1, slot, bounds=None):
    """A brace running corner to corner, as a parallelogram prism.

    ``bounds`` clips it to the leaf edges. A brace's width pushes its corners sideways
    past its endpoints, so an unclipped one overhangs the leaf and the door binds on
    the lining - which is also how a real brace is cut, flush to the boards.
    """
    du, dv = u1 - u0, v1 - v0
    length = math.hypot(du, dv) or 1.0
    nu, nv = -dv / length * width / 2.0, du / length * width / 2.0
    ends = [(u0 + nu, v0 + nv), (u1 + nu, v1 + nv), (u1 - nu, v1 - nv), (u0 - nu, v0 - nv)]
    if bounds:
        lo, hi = bounds
        ends = [(min(max(u, lo), hi), v) for u, v in ends]
    back = [(u, y1, v) for u, v in ends]
    front = [(u, y0, v) for u, v in ends]
    part.face(front, slot)
    part.face(list(reversed(back)), slot)
    for i in range(4):
        j = (i + 1) % 4
        part.face([back[i], back[j], front[j], front[i]], slot)


def _braced_leaf(part, lw, lh, t):
    """Boards on the face; ledges and a diagonal brace behind, as the real thing is."""
    front, mid = -t, -t * 0.45
    _boards(part, lw, lh, front, mid)
    low, high = 0.13 * lh, 0.80 * lh
    ledge = 0.135
    for v in (low, high):
        part.plate(0.0, lw, v, v + ledge, mid, 0.0, "leaf")
    _diagonal(part, 0.02, low + ledge, lw - 0.02, high, 0.115, mid, 0.0, "leaf",
              bounds=(0.0, lw))
    _straps(part, lw, lh, t, (low + ledge / 2, high + ledge / 2))


def _banded_leaf(part, lw, lh, t):
    """Heavy iron bands straight across the face, studded - a fortified door."""
    front, mid = -t, -t * 0.42
    _boards(part, lw, lh, front, mid)
    for v in (0.09 * lh, 0.50 * lh, 0.87 * lh):
        part.plate(0.0, lw, v, v + 0.150, mid, 0.0, "leaf")     # backing ledge
        band_face = front - 0.018
        # Flush with the boards: a band that wraps the edge would make the leaf wider
        # than the clear opening and the door would bind on the lining.
        part.plate(0.0, lw, v + 0.006, v + 0.144,
                   band_face, front, "hardware")                # the band itself
        studs = max(3, int(lw / 0.16))
        for i in range(studs):
            u = 0.055 + (lw - 0.11) * i / max(1, studs - 1)
            # Studs sit on the BAND's outer face; putting them on the board face buries
            # them inside the band, which is thicker than the stud is tall.
            _clavo(part, u, v + 0.075, band_face)
    _straps(part, lw, lh, t, ())


def _straps(part, lw, lh, t, heights):
    """Tapered strap hinges reaching well across the leaf, studded along their length."""
    front = -t
    for v in heights:
        _taper_bar(part, 0.012, lw * 0.62, v, 0.105, 0.052, front - 0.013, front)
        for i in range(4):
            _clavo(part, 0.055 + (lw * 0.52) * i / 3.0, v, front - 0.013)
    for v in (0.06 * lh, 0.94 * lh):        # pintle plates at top and bottom of the stile
        part.plate(0.010, 0.085, v - 0.045, v + 0.045, front - 0.012, front, "hardware")


def _taper_bar(part, u0, u1, v_c, h0, h1, y0, y1, slot="hardware"):
    prof = [(u0, v_c - h0 / 2), (u1, v_c - h1 / 2), (u1, v_c + h1 / 2), (u0, v_c + h0 / 2)]
    back = [(u, y1, v) for u, v in prof]
    front = [(u, y0, v) for u, v in prof]
    part.face(front, slot)
    part.face(list(reversed(back)), slot)
    for i in range(4):
        j = (i + 1) % 4
        part.face([back[i], back[j], front[j], front[i]], slot)


def _clavo(part, u, v, y_face, size=0.030, rise=0.017):
    """A stud head: a square frustum standing proud of the face."""
    h = size / 2.0
    base = [(u - h, y_face, v - h), (u + h, y_face, v - h),
            (u + h, y_face, v + h), (u - h, y_face, v + h)]
    k = h * 0.55
    top = [(u - k, y_face - rise, v - k), (u + k, y_face - rise, v - k),
           (u + k, y_face - rise, v + k), (u - k, y_face - rise, v + k)]
    part.face(list(reversed(base)), "hardware")
    part.face(top, "hardware")
    for i in range(4):
        j = (i + 1) % 4
        part.face([base[i], base[j], top[j], top[i]], "hardware")


def _ring_pull(part, lw, lh, t):
    """Backplate and a hanging ring - the single biggest change from a lever."""
    u, v = lw - 0.10, min(1.02, lh * 0.46)
    front = -t
    part.plate(u - 0.052, u + 0.052, v - 0.052, v + 0.052, front - 0.010, front, "hardware")
    _torus(part, u, v - 0.085, front - 0.018, radius=0.058, tube=0.011)


def _torus(part, u, v, y, radius, tube, around=16, thick=6):
    def point(i, j):
        a = 2.0 * math.pi * i / around
        b = 2.0 * math.pi * j / thick
        r = radius + tube * math.cos(b)
        return (u + r * math.cos(a), y + tube * math.sin(b), v + r * math.sin(a))
    for i in range(around):
        for j in range(thick):
            part.face([point(i, j), point(i + 1, j),
                       point(i + 1, j + 1), point(i, j + 1)], "hardware")


def _bake_hinge(leaf, spec):
    """Keyframe a normalised closed -> open clip, and record the pivot contract.

    Both are shipped on purpose: the clip covers doors whose motion a convention could
    never describe, and the metadata lets a toolkit drive the node directly when it
    wants interruption or partial opening.
    """
    anim = spec.animation
    if anim.kind != "hinge":
        return
    axis = {"x": 0, "y": 1, "z": 2}[anim.axis]
    swing = anim.open_degrees * (1.0 if spec.hinge == "left" else -1.0)

    leaf.rotation_mode = "XYZ"
    leaf.rotation_euler[axis] = 0.0
    leaf.keyframe_insert("rotation_euler", index=axis, frame=1)
    leaf.rotation_euler[axis] = math.radians(swing)
    leaf.keyframe_insert("rotation_euler", index=axis, frame=anim.frames)
    if leaf.animation_data and leaf.animation_data.action:
        leaf.animation_data.action.name = anim.clip
    leaf.rotation_euler[axis] = 0.0          # ship it closed

    leaf["prefab_pivot"] = "hinge"
    leaf["prefab_open_axis"] = anim.axis
    leaf["prefab_open_degrees"] = swing
    leaf["prefab_clip"] = anim.clip

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(scene.frame_end, anim.frames)


# --- windows ----------------------------------------------------------------

def _window(spec, report):
    part = _Part()
    _lining(part, spec, sill_board=True)
    _casing(part, spec, wrap_sill=True)

    x0, x1, z0, z1, ht, f = _bounds(spec)
    L, bar = f.lining, spec.glazing_bar
    left, right = x0 + L, x1 - L
    bottom, top = z0 + L, z1 - L
    glass_y = -ht + f.rebate
    cols, rows = PATTERNS.get(spec.pattern or "single", (1, 1))

    part.box(left, right, glass_y, glass_y + 0.006, bottom, top, "glass")
    for i in range(1, cols):                       # glazing bars, proud of the glass
        centre = left + (right - left) * i / cols
        part.box(centre - bar / 2, centre + bar / 2, glass_y - 0.010, glass_y + 0.016,
                 bottom, top, "frame")
    for j in range(1, rows):
        centre = bottom + (top - bottom) * j / rows
        part.box(left, right, glass_y - 0.010, glass_y + 0.016,
                 centre - bar / 2, centre + bar / 2, "frame")
    return part.finish(spec.name, spec, report)
