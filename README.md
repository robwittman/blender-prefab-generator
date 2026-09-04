# blender-prefab-generator

Generate a library of modular game assets from a config file. You describe a matrix of
sizes, openings, materials and roof pitches; the generator expands it and drives Blender
headlessly to build every combination as an individual, self-contained prefab — with
textures, previews, and a manifest for an asset picker.

Built to seed a prefab library for a creator toolkit, so creators can assemble levels
without managing models or materials themselves.

## Requirements

- **Blender 4.2+** (found automatically at the usual install paths, or set `$BLENDER` /
  pass `--blender`)
- **Python 3.9+** for the CLI (`pyyaml` comes in with the install). Blender's own
  bundled Python runs the geometry and needs nothing installed — the Blender-side
  modules import only the standard library, which is why the split exists.

## Install

```bash
python3 -m pip install -e ".[dev]"     # editable: code changes take effect immediately
```

That puts a `prefabgen` command on your PATH, runnable from any directory. Paths in a
config resolve relative to *the config file*, not your shell, so output always lands
beside the config no matter where you invoke it:

```bash
cd ~/anywhere
prefabgen build ~/Repos/blender-prefab-generator/example/config/walls.yaml
```

Using **asdf**? Console scripts need a shim before they appear on PATH:

```bash
asdf reshim python
```

Without installing, `python3 -m prefabgen ...` works from the repo root.

## Quick start

```bash
prefabgen textures example/config/walls.yaml   # what textures resolved
prefabgen plan     example/config/walls.yaml   # what would be generated
prefabgen build    example/config/walls.yaml   # generate it
```

The bundled example builds 68 wall prefabs (walls, gables, corners), 68 roof prefabs
and 14 doors/windows.

Iterating? Thumbnails dominate the runtime, so skip them:

```bash
prefabgen build example/config/walls.yaml --no-thumbnails
prefabgen build example/config/walls.yaml --filter '*_brick' --no-thumbnails
```

`--filter` is a glob over prefab names or ids. Builds are incremental, so the second
command rebuilds the brick pieces and leaves the rest alone — and the manifest still
describes the whole library, because the prefabs it skipped are recovered from the
build cache rather than dropped.

### Showcase images

```bash
prefabgen showcase example/config/walls.yaml example/config/roofs.yaml example/config/joinery.yaml
```

Pools any number of configs and renders three images for playtester feedback:

| image | what it shows |
|---|---|
| `gallery.png` | every piece, labelled, at **true relative scale** |
| `buildings.png` | three sample buildings assembled from the kit |
| `hero.png` | one building, framed close, at high resolution |

The hero shot exists because thumbnails and wide layouts flatten the detail that relief
and 4K textures actually carry — at 2800x2000 the plank courses and roof tiles read
properly. It defaults to `brown_planks` walls with a `shingle_ceramic` hip roof and
varies the wall pieces around the footprint; both materials fall back to whatever the
configs contain.

```bash
--only gallery|buildings|hero        # render just one
--width / --height / --samples       # gallery and buildings
--hero-width / --hero-height / --hero-samples
--hero-wall <material> --hero-roof <material>
```

## Output

```
build/
  manifest.json                 # the catalogue an asset picker reads
  models/<name>.blend
  thumbnails/<name>.png
```

`manifest.json` carries per prefab: stable id, display name, category, tags, dimensions,
openings, material, vertex count and file paths. It is sorted by id and contains no
timestamps, so an unchanged rebuild produces an identical file and diffs stay readable.

Output format is `blend` by default (Godot imports it natively); `glb` and `fbx` are also
supported, individually or as a list.

## How it works

The matrix expansion, config validation and manifest live in **ordinary Python outside
Blender** — fast, unit-testable, no `bpy` import. Blender is invoked once with a JSON
blob of fully-resolved specs and does only geometry, materials and rendering.

```
prefabgen/
  matrix.py      cartesian expansion, exclude rules, name templating
  config.py      config -> resolved specs; includes, materials, pitches, relief
  cache.py       what has to be rebuilt, and the report entries of what did not
  spec.py        WallSpec / RoofSpec / MaterialSpec, validation
  ids.py         regeneration-stable prefab ids
  textures.py    texture map discovery
  manifest.py    the library catalogue
  cli.py         plan / build / textures / showcase
  blender/       runs INSIDE Blender:
    run.py         entry point: build specs, render, export
    build.py       wall geometry (bmesh)
    wallparts.py   gable triangles and L-shaped corner segments
    roof.py        roof geometry: slab, ridge, hip, valley, caps
    joinery.py     doors and windows: lining, casing, leaf, ironwork, glazing, hinge
    materials.py   Principled BSDF from texture maps
    relief.py      real geometric relief from a height map
    thumbnail.py   per-prefab preview renders
    showcase.py    gallery / sample-building layout helpers
    showcase_run.py  entry point for the showcase renders
    export.py      .blend / .glb / .fbx writers
```

## Things worth knowing

**Mating planes are exact.** Everything a neighbouring module touches stays perfectly
planar: wall side faces, roof plumb cuts, and displaced surfaces alike. Relief is
displaced along a face's own axis rather than along vertex normals, so border
vertices stay on the mating plane however far they move. A flat wall declares two
face groups on Y; a corner has faces in two axes and declares four — alignment is exact by
construction, and surface detail runs unbroken across a joint.

**Prefab ids are stable across regeneration.** Creator-authored levels reference them, so
ids derive from the *semantic* axis values with numerics normalised to integer
millimetres (`wall.2000x2500x200.door.brick`), never from the filename or display name.
Renaming a prefab does not break a level. Duplicate ids are a hard error.

**Pitches are a shared library too.** `pitches:` sits at the top level (`roof.pitches:`
still works), because a gable and the roof closing it must use the identical angle.
Apex height is `(W/2)·tanθ` for a centred gable and `W·tanθ` for a half — with exact
ratio pitches, every apex lands on the grid.

**A corner is one mesh, not two walls.** Four equal-length walls meeting at a corner put
coplanar faces against each other and z-fight into black bars. The L-shaped corner
segment has no internal join to fight with. It anchors on its *outer corner*, so a 4m
side becomes corner(1m) + wall(2m) + corner(1m).

**Builds are incremental.** A prefab's output is a pure function of three things: its
resolved spec, the bytes of every texture that spec names, and the Blender-side code
that turns one into the other. All three are hashed into one key per prefab, so
changing a single material rebuilds only the prefabs that use it:

```
$ prefabgen build example/config/walls.yaml       # after editing one material
[prefabgen] building 34 of 68 prefab(s): 34 spec, textures or builder changed
[prefabgen] reused 34 prefab(s) from the build cache
```

The key covers the whole spec, so it catches far more than materials — a changed wall
width, a new pitch, a different output format, an edited `build.py`. Textures are
compared by **content**, re-read only when size or mtime moves: a `git checkout` that
restores a texture byte-for-byte does not trigger a rebuild, and a 4K set is not
re-hashed every time. A prefab whose output file has been deleted is rebuilt whatever
its key says. `--no-cache` forces a full rebuild.

Thumbnail settings are deliberately *not* part of the key. Iterating with
`--no-thumbnails` and then doing one full build is the documented workflow, and folding
the thumbnail size in would make that last build a full rebuild of geometry that never
changed — so a missing thumbnail is checked separately, and only when thumbnails are
actually wanted.

The cache stores each prefab's **build report entry**, not just its hash, and that is
what makes a partial build safe. The manifest is composed from the whole plan, so
entries for the prefabs a run did not touch have to come from somewhere; without them,
editing one material would quietly drop the other 140 prefabs out of the catalogue —
worse than the full rebuild it replaced. The cache lives at
`build/.prefabgen-cache.json`; deleting it costs a rebuild and nothing else.

Prefabs that a config change removed are reported, not deleted — their `.blend` files
stay in `models/` until you clear them out.

**Configs share with `include:`.** Pitches a gable and a roof must agree on, openings a
wall cuts and a door fills — anything two builds have to keep identical goes in one file
and every kit pulls it in:

```yaml
include: common.yaml          # or a list: [common.yaml, ../studio/house-style.yaml]

output:
  manifest: manifest-roofs.json   # this kit's own name; the rest of `output` is shared
```

Includes merge in the order listed and the including file wins over all of them, key by
key: mappings merge, anything else — a list, a scalar — replaces outright. So a shared
file may carry a whole `parts:` list, but a config declaring its own replaces it rather
than appending, which keeps "what does this build actually contain" answerable from one
place. Includes may nest; a cycle is an error.

Paths inside an included file stay relative to *that file*, so a shared config can live
in its own folder without every kit knowing where that folder is. The bundled example
uses this: [example/config/common.yaml](example/config/common.yaml) holds the output
settings, texture root, pitches, openings and defaults that walls, roofs and joinery
all share.

**Defaults are namespaced by part type.** `thickness` means 0.2 to a wall and 0.18 to a
roof; `origin` means `bottom_center` to a wall and `footprint_center` to a roof. A flat
`defaults:` block therefore *cannot* be shared between kits that build both — the two
kits collide on the key rather than sharing it, and the loser is silent. Qualify the key
with the part type it belongs to:

```yaml
defaults:
  min_border: 0.1                 # unqualified: applies to every part
  wall:   { thickness: 0.2,  origin: bottom_center }
  roof:   { thickness: 0.18, origin: footprint_center }
  door:   { wall_thickness: 0.2 }
```

Resolution runs part key → `defaults.<type>.<key>` → `defaults.<key>` → the built-in
default, so unqualified keys stay the right home for genuinely cross-cutting settings
and an existing flat block keeps working unchanged. The type names are the part types:
`wall`, `roof`, `door`, `window`, `gable`, `corner`.

Everything else the top level holds is already namespaced by construction —
`materials:`, `pitches:` and `openings:` are maps keyed by a name you chose, so two
includes only collide if they define *the same name*, and `output:`, `textures:` and
`library:` are singular per build, where the including file overriding them is the
point. `defaults:` was the one block whose keys meant different things to different
readers.

**Openings are a shared library.** `openings:` sits at the top level; walls *cut* them
and joinery *fills* them from the same definition, so a door cannot silently stop
fitting the hole it was built for. Same reasoning as named pitches.

**A door's real deliverable is its pivot, not its animation.** Doors emit a hierarchy —
a static `frame` and a `leaf` whose origin sits exactly on the hinge axis — plus both a
baked `open` clip and pivot metadata in glTF `extras`:

```gdscript
if player: player.seek(t)                      # scrub the clip for partial opening
else:      leaf.rotation.y = t * open_radians  # or drive the node directly
```

Shipping both is deliberate. The clip covers doors whose motion no convention could
describe (a modder's sliding or folding door); the metadata lets a toolkit drive the
node when it wants interruption or physics. `export_extras` is enabled explicitly — it
defaults to *off*, and without it the pivot contract never reaches the engine.

**Give roof pitches as a ratio, not degrees.** `{ rise: 1, run: 2 }` is exactly
`atan(0.5)`; writing `26.565` makes a 2m run rise 0.999998m — the exact drift a modular
kit exists to prevent.

**Textures are auto-discovered.** Unzip an ambientCG or Poly Haven set into
`textures/<material>/` and it is found by filename token, in any image format, with
`NormalGL` preferred over `NormalDX` (and the green channel flipped if only DX exists).
Overridable per role. See [example/textures/README.md](example/textures/README.md).

**Relief is real geometry, not a normal map.** A normal map cannot change a silhouette.
Opting a material into `relief` displaces actual vertices from the height map — which is
consumed at build time and never embedded in the shipped prefab. It is per-material
because it costs vertices: a 2×2.5m wall goes from 8 to ~4,200.

## Tests

```bash
python3 -m pytest tests -q      # 126 tests
```

Covers matrix expansion, exclude rules, stable ids, texture discovery across naming
conventions, relief config, config includes, scoped defaults, incremental-build
invalidation, the plan/textures reporting commands, and manifest shape. Geometry is verified separately by
building and measuring the meshes (manifold, volumes, mating-plane drift).

## Known gaps

- **Relief does not apply to roof or joinery pieces yet** — it warns and leaves them flat.
  Walls, gables and corners all have it.
- **`.blend` cannot be loaded at runtime.** Godot's `.blend` import is an editor-only
  pipeline that shells out to Blender, so mods loaded at runtime need `.glb`
  (`format: [blend, glb]`). Verify what your loader accepts before shipping.
- Windows are fixed glazing; an opening sash would reuse the door's hinge machinery.
- Hip and valley trim caps overhang their footprint, so they do not bound to a grid cell
  the way slabs and corners do.
