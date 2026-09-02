"""Entry point executed inside Blender:

    blender --background --factory-startup --python showcase_run.py -- --job job.json

Renders two sharable images: a gallery of every piece at true relative scale, and a
handful of sample buildings assembled from them.
"""
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from prefabgen.blender import showcase as S  # noqa: E402
from prefabgen.spec import spec_from_dict  # noqa: E402

HALF_PI = math.pi / 2
LAP = 0.004      # 4mm: enough to break coplanarity, invisible at any sane zoom


# --- finding pieces by what they are, not by name ---------------------------

def find(specs, **kw):
    spec = try_find(specs, **kw)
    if spec is None:
        raise LookupError(f"no prefab matches {kw}")
    return spec


def try_find(specs, **kw):
    for spec in specs:
        if all(_match(spec, k, v) for k, v in kw.items()):
            return spec
    return None


def largest(specs, key, **kw):
    """Biggest match by ``key``. find() returns the first match, which is the smallest
    piece in the matrix - fine for a lookup, wrong for a showcase."""
    matches = [x for x in specs if all(_match(x, k, v) for k, v in kw.items())]
    if not matches:
        raise LookupError(f"no prefab matches {kw}")
    return max(matches, key=lambda x: getattr(x, key))


def catalogue(specs, kind, attr):
    """Distinct values of ``attr`` across one part type, in config order.

    The sample buildings pick their materials, pitches and sizes from what the configs
    actually contain rather than naming them, so editing a config cannot leave the
    showcase referring to a material that no longer exists.
    """
    seen = []
    for spec in specs:
        if spec.type != kind:
            continue
        value = spec.material.name if attr == "material" else getattr(spec, attr, None)
        if value is not None and value not in seen:
            seen.append(value)
    return seen


def _match(spec, key, value):
    if key == "material":
        return spec.material.name == value
    if key == "opening":
        kinds = [o.kind for o in getattr(spec, "openings", ())]
        return (kinds[0] if kinds else "solid") == value
    actual = getattr(spec, key, None)
    if isinstance(actual, float) or isinstance(value, (int, float)):
        try:
            return abs(float(actual) - float(value)) < 1e-9
        except (TypeError, ValueError):
            return False
    return actual == value


# --- gallery ----------------------------------------------------------------

def gallery(specs, path, width, height, samples, columns=None):
    S.scene(samples)
    label_rot = S.VIEW.to_track_quat("-Z", "Y").to_euler()

    ordered = sorted(specs, key=lambda s: (s.type != "wall", getattr(s, "piece", ""),
                                           s.material.name, s.name))
    built = [(spec, S.make(spec)) for spec in ordered]

    footprint = tall = 0.0
    for _spec, obj in built:
        lo, hi = S.bounds(obj)
        footprint = max(footprint, hi.x - lo.x, hi.y - lo.y)
        tall = max(tall, hi.z - lo.z)

    # Lay the grid out along the CAMERA's screen axes rather than world X/Y. On world
    # axes an angled camera turns the grid into a diagonal smear that wastes most of
    # the frame; aligned to the view it reads as a contact sheet.
    right = S.VIEW.cross(Vector((0, 0, 1)))
    right.normalize()
    up = Vector((0, 0, 1)).cross(right)
    up.normalize()

    col_step = footprint * 1.3
    # Rows need clearance for how far a piece LEANS up the screen. A vertical metre
    # projects cos(elevation) up; a ground metre between rows projects sin(elevation)
    # down. So a piece of height h eats h*cot(elevation) of row spacing - at this 35
    # degree view that is 1.4x its height, not the fraction it looks like.
    lean = math.sqrt(max(1e-6, 1.0 - S.VIEW.z ** 2)) / max(1e-6, abs(S.VIEW.z))
    row_step = footprint * 1.15 + tall * lean * 1.05

    # Rows recede across the ground, so their on-screen height is foreshortened by the
    # view's vertical component; ignoring that picks too many columns and leaves the
    # bottom of the frame empty.
    squash = abs(S.VIEW.z) or 1.0
    cols = columns or max(1, round(math.sqrt(len(built) * (width / height) *
                                             (row_step * squash / col_step))))
    rows = math.ceil(len(built) / cols)

    for i, (spec, obj) in enumerate(built):
        col, row = i % cols, i // cols
        offset = (right * ((col - (cols - 1) / 2) * col_step)
                  + up * (((rows - 1) / 2 - row) * row_step))
        S.sit_at(obj, offset.x, offset.y)
        # Keep the label pinned near its own piece rather than scaling with row_step.
        anchor = offset - up * (footprint * 0.62)
        S.label(S.short_label(spec), (anchor.x, anchor.y, footprint * 0.34),
                footprint * 0.105, label_rot)

    S.ground(max(cols * col_step, rows * row_step) * 2.6)
    S.aim([o for _s, o in built], Vector((0, 0, tall * 0.30)),
          pad=1.12, aspect=width / height)
    print(f"GALLERY {len(built)} pieces, {cols}x{rows}, cell {col_step:.2f}x{row_step:.2f}m")
    return S.render(path, width, height)


# --- sample buildings -------------------------------------------------------

def _walls(specs, cx, cy, w, d, z, height, material, openings):
    """Four walls around a w x d footprint. openings = (south, north, east, west)."""
    out = []
    for want, (length, sx, sy, rot) in zip(openings, [
            (w, 0, -1, 0.0), (w, 0, 1, math.pi),
            (d, 1, 0, HALF_PI), (d, -1, 0, -HALF_PI)]):
        spec = None
        for opening in (want, "solid"):          # fall back if that opening isn't in the kit
            spec = try_find(specs, type="wall", width=length, height=height,
                            opening=opening, material=material)
            if spec:
                break
        if spec is None:
            raise LookupError(f"no {length}x{height} {material} wall")
        # Inset by half a wall so the building's OUTER faces land on the grid line the
        # roof is sized to; centring the walls on it leaves them proud of the eaves.
        #
        # Then lap the side walls a hair further in. All four walls are the same length,
        # so a side wall's END face lands exactly coplanar with the outer face of the
        # wall it meets, and the two z-fight into black bars down every corner. The kit
        # has no corner post to hide that join, so the showcase laps them instead.
        # Two coplanar pairs form at every corner, not one: a side wall's end face
        # meets the front wall's outer face, AND the front wall's end face meets the
        # side wall's outer face. Lap the sides in and the fronts out to separate both.
        ox = sx * (w / 2 - spec.thickness / 2 - LAP)
        oy = sy * (d / 2 - spec.thickness / 2 + LAP)
        out.append(S.place(S.make(spec), cx + ox, cy + oy, z, rot))
    return out


def _hipped(specs, cx, cy, run, z, pitch, material):
    """Four hip corners meeting at the centre make a pyramid over a 2*run square."""
    spec = find(specs, type="roof", piece="hip", run=run, pitch=pitch, material=material)
    # A roof piece's z=0 is its TOP surface at the eave, so lift it by its own vertical
    # thickness to rest the underside on the wall plate instead of sinking into it.
    z += spec.vertical_thickness
    return [S.place(S.make(spec), cx + dx, cy + dy, z, rot)
            for (dx, dy, rot) in [(-run / 2, -run / 2, 0.0), (run / 2, -run / 2, HALF_PI),
                                  (run / 2, run / 2, math.pi), (-run / 2, run / 2, -HALF_PI)]]


def _gabled(specs, cx, cy, span, run, z, pitch, material):
    """Two opposing slabs plus a ridge cap."""
    slab = find(specs, type="roof", piece="slab", span=span, run=run,
                pitch=pitch, material=material)
    z += slab.vertical_thickness          # rest the eave underside on the wall plate
    out = [S.place(S.make(slab), cx, cy - run / 2, z, 0.0),
           S.place(S.make(slab), cx, cy + run / 2, z, math.pi)]
    ridge = try_find(specs, type="roof", piece="ridge", span=span, pitch=pitch, material=material)
    if ridge:
        out.append(S.place(S.make(ridge), cx, cy, z + slab.rise, 0.0))
    return out


def _designs(specs):
    """Three buildings described in terms of what the kit actually offers."""
    wall_mats = catalogue(specs, "wall", "material") or ["Default"]
    roof_mats = catalogue(specs, "roof", "material") or ["Default"]
    pitches = catalogue(specs, "roof", "pitch") or ["steep"]
    heights = sorted(catalogue(specs, "wall", "height"))
    h = heights[0] if heights else 2.5

    def wm(i):
        return wall_mats[i % len(wall_mats)]

    def rm(i):
        return roof_mats[i % len(roof_mats)]

    steep = pitches[-1]
    shallow = pitches[0]

    def cottage(cx):
        hip = largest(specs, "run", type="roof", piece="hip", pitch=steep, material=rm(0))
        size = hip.run * 2
        made = _walls(specs, cx, 0, size, size, 0, h, wm(0),
                      ("door", "solid", "window", "window"))
        made += _hipped(specs, cx, 0, hip.run, h, steep, rm(0))
        return made, size, f"Hipped cottage\n{wm(0)} walls, {steep} {rm(0)} hip roof"

    def shed(cx):
        slab = largest(specs, "span", type="roof", piece="slab", run=min(
            x.run for x in specs if x.type == "roof" and x.piece == "slab"),
            pitch=shallow, material=rm(1))
        made = _walls(specs, cx, 0, slab.span, slab.run * 2, 0, h, wm(1),
                      ("window", "solid", "solid", "door"))
        made += _gabled(specs, cx, 0, slab.span, slab.run, h, shallow, rm(1))
        return made, slab.span, f"Gabled shed\n{wm(1)} walls, {shallow} {rm(1)} gable"

    def tower(cx):
        # Only hips: a ridge's `run` is its cap width, which is not a footprint size.
        runs = sorted({x.run for x in specs if x.type == "roof" and x.piece == "hip"})
        hip = find(specs, type="roof", piece="hip", run=runs[0], pitch=shallow, material=rm(0))
        size = hip.run * 2
        made = _walls(specs, cx, 0, size, size, 0, h, wm(0), ("door", "solid", "solid", "solid"))
        made += _walls(specs, cx, 0, size, size, h, h, wm(1), ("window", "window", "solid", "solid"))
        made += _hipped(specs, cx, 0, hip.run, h * 2, shallow, rm(0))
        return made, size, f"Two-storey tower\nmixed walls, {shallow} {rm(0)} hip"

    return [cottage, shed, tower]


def buildings(specs, path, width, height, samples):
    S.scene(samples)
    label_rot = S.VIEW.to_track_quat("-Z", "Y").to_euler()
    made, plans, cursor, skipped = [], [], 0.0, []

    for design in _designs(specs):
        try:
            pieces, size, text = design(cursor + 3.0)
        except LookupError as exc:
            skipped.append(str(exc))
            continue
        made += pieces
        plans.append((cursor + 3.0, size, text))
        cursor += size + 5.0

    if not made:
        raise SystemExit(f"could not assemble any sample building: {'; '.join(skipped)}")
    for reason in skipped:
        print(f"[prefabgen] skipped a sample building: {reason}")

    # Hang labels from above the ground: a billboard anchored at z~0 extends downward
    # in screen space and is swallowed by the ground plane.
    for cx, size, text in plans:
        S.label(text, (cx, -size / 2 - 2.6, 1.30), 0.42, label_rot)

    centre = Vector((cursor / 2, 0, 1.8))
    S.ground(cursor * 2.6 + 40, centre=(centre.x, 0))
    S.aim(made, centre, pad=1.12, aspect=width / height)
    print(f"BUILDINGS {len(plans)} buildings, {len(made)} pieces")
    return S.render(path, width, height)


def main(argv):
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    with open(args[args.index("--job") + 1]) as fh:
        job = json.load(fh)
    specs = [spec_from_dict(d) for d in job["specs"]]

    if job.get("gallery"):
        print(f"[prefabgen] gallery -> {gallery(specs, job['gallery'], job['width'], job['height'], job['samples'])}")
    if job.get("buildings"):
        print(f"[prefabgen] buildings -> {buildings(specs, job['buildings'], job['width'], job['height'], job['samples'])}")


main(sys.argv)
