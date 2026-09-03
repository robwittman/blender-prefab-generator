"""Gable and corner wall pieces. Runs INSIDE Blender.

A gable is a triangular prism closing a roof end; its apex comes from the SHARED pitch
library, so it cannot disagree with the roof sitting on it.

A corner is an L in plan, extruded, built as ONE mesh. That is the whole point: four
equal-length walls meeting at a corner put coplanar faces against each other and
z-fight into black bars down every corner, and a single mesh has no internal join to
fight with.

Both subdivide to the relief resolution when their material asks for it, using the same
column count on every row so the grid stays watertight.
"""
import math

import bmesh
import bpy

from .build import _assign_materials, _uv_project, _vert

EPS = 1e-6
RELIEF_PREFIX = "_relief_"


class _Mesh:
    def __init__(self):
        self.bm = bmesh.new()
        self.cache = {}
        self.slots = []

    def face(self, points):
        """Add a face, collapsing any degenerate edge so apex fans stay valid."""
        clean = []
        for p in points:
            key = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
            if not clean or key != clean[-1]:
                clean.append(key)
        if len(clean) > 2 and clean[0] == clean[-1]:
            clean.pop()
        if len(clean) < 3:
            return
        self.bm.faces.new([_vert(self.bm, self.cache, p) for p in clean])
        self.slots.append(0)

    def finish(self, spec, report):
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:])
        _uv_project(self.bm)
        mesh = bpy.data.meshes.new(spec.name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        obj = bpy.data.objects.new(spec.name, mesh)
        _assign_materials(mesh, spec, self.slots, report)
        obj["prefab_id"] = mesh["prefab_id"] = spec.id
        obj["prefab_category"] = spec.category
        mesh.update()
        return obj


def _steps(span, resolution):
    if not resolution or resolution <= 0:
        return 1
    return max(1, int(math.ceil(span / resolution - 1e-9)))


def _resolution(spec):
    relief = getattr(spec.material, "relief", None)
    return relief.resolution if relief else None


def _lerp(a, b, f):
    return a + (b - a) * f


# --- gables -----------------------------------------------------------------

def build_gable(spec, report=None) -> bpy.types.Object:
    W, t, apex = spec.width, spec.thickness, spec.apex
    half_t = t / 2.0
    res = _resolution(spec)

    def extent(z):
        """Left and right x at height z, following the sloping edge exactly."""
        f = 0.0 if apex <= EPS else z / apex
        if spec.shape == "full":
            half = (W / 2.0) * (1.0 - f)
            return -half, half
        if spec.shape == "left":            # apex at +x
            return -W / 2.0 + W * f, W / 2.0
        return -W / 2.0, W / 2.0 - W * f    # "right": apex at -x

    rows = _steps(apex, res)
    # One column count for every row: varying it per row would leave T-junctions
    # between rows and the mesh would not be watertight.
    cols = _steps(W, res)

    m = _Mesh()
    for j in range(rows):
        z0, z1 = apex * j / rows, apex * (j + 1) / rows
        l0, r0 = extent(z0)
        l1, r1 = extent(z1)
        for i in range(cols):
            a0, b0 = _lerp(l0, r0, i / cols), _lerp(l0, r0, (i + 1) / cols)
            a1, b1 = _lerp(l1, r1, i / cols), _lerp(l1, r1, (i + 1) / cols)
            m.face([(a0, -half_t, z0), (b0, -half_t, z0), (b1, -half_t, z1), (a1, -half_t, z1)])
            m.face([(a0, half_t, z0), (b0, half_t, z0), (b1, half_t, z1), (a1, half_t, z1)])
        # sloping / vertical edges, subdivided to match so there are no T-junctions
        m.face([(l0, -half_t, z0), (l0, half_t, z0), (l1, half_t, z1), (l1, -half_t, z1)])
        m.face([(r0, -half_t, z0), (r1, -half_t, z1), (r1, half_t, z1), (r0, half_t, z0)])

    l0, r0 = extent(0.0)
    for i in range(cols):                    # base, matching the skin's column edges
        a, b = _lerp(l0, r0, i / cols), _lerp(l0, r0, (i + 1) / cols)
        m.face([(a, -half_t, 0.0), (a, half_t, 0.0), (b, half_t, 0.0), (b, -half_t, 0.0)])
    return m.finish(spec, report)


# --- corners ----------------------------------------------------------------

def build_corner(spec, report=None) -> bpy.types.Object:
    arm, t, h = spec.arm, spec.thickness, spec.height
    res = _resolution(spec)
    # L in plan, counter-clockwise from the outer corner at the origin.
    outline = [(0.0, 0.0), (arm, 0.0), (arm, t), (t, t), (t, arm), (0.0, arm)]

    rows = _steps(h, res)
    m = _Mesh()
    boundary = []                            # subdivided plan boundary, shared with caps
    for k, (p, q) in enumerate(zip(outline, outline[1:] + outline[:1])):
        cols = _steps(math.hypot(q[0] - p[0], q[1] - p[1]), res)
        pts = [(_lerp(p[0], q[0], i / cols), _lerp(p[1], q[1], i / cols)) for i in range(cols)]
        boundary.extend(pts)
        for i in range(cols):
            a = pts[i]
            b = pts[i + 1] if i + 1 < cols else q
            for j in range(rows):
                z0, z1 = h * j / rows, h * (j + 1) / rows
                m.face([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)])

    cx = sum(p[0] for p in boundary) / len(boundary)
    cy = sum(p[1] for p in boundary) / len(boundary)
    for i, a in enumerate(boundary):         # fan the caps so they meet every boundary vert
        b = boundary[(i + 1) % len(boundary)]
        m.face([(cx, cy, 0.0), (b[0], b[1], 0.0), (a[0], a[1], 0.0)])
        m.face([(cx, cy, h), (a[0], a[1], h), (b[0], b[1], h)])

    obj = m.finish(spec, report)
    _corner_relief_groups(obj, spec)
    return obj


def _corner_relief_groups(obj, spec):
    """Declare which faces relief may displace, and along which axis.

    A corner has faces in two axes, so a single front/back split cannot describe it.
    The mating planes - the arm ends at x=arm and y=arm - are deliberately absent, so
    nothing displaces off the surfaces a neighbouring wall butts against.
    """
    if not getattr(spec.material, "relief", None):
        return
    t, arm = spec.thickness, spec.arm
    wanted = {"-x": lambda c: abs(c.x) < EPS, "+x": lambda c: abs(c.x - t) < EPS,
              "-y": lambda c: abs(c.y) < EPS, "+y": lambda c: abs(c.y - t) < EPS}
    for tag, on_plane in wanted.items():
        members = [v.index for v in obj.data.vertices if on_plane(v.co)]
        if members:
            obj.vertex_groups.new(name=RELIEF_PREFIX + tag).add(members, 1.0, "REPLACE")
