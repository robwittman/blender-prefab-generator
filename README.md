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
- **Python 3.9+** with `pyyaml`, for the CLI. Blender's own bundled Python runs the
  geometry, and needs nothing installed.

## Quick start

```bash
python3 -m prefabgen textures example/config/walls.yaml   # what textures resolved
python3 -m prefabgen plan     example/config/walls.yaml   # what would be generated
python3 -m prefabgen build    example/config/walls.yaml   # generate it
```

The bundled example builds 28 wall prefabs and 68 roof prefabs.

Iterating? Thumbnails dominate the runtime, so skip them:

```bash
python3 -m prefabgen build example/config/walls.yaml --no-thumbnails
python3 -m prefabgen build example/config/walls.yaml --filter '*_brick' --no-thumbnails
```

`--filter` is a glob over prefab names or ids. Note a filtered build rewrites the
manifest with only what it built, so run an unfiltered build before shipping.

### Showcase images

```bash
python3 -m prefabgen showcase example/config/walls.yaml example/config/roofs.yaml
```

Pools any number of configs and renders `gallery.png` (every piece, labelled, at **true
relative scale**) and `buildings.png` (sample buildings assembled from the kit). Useful
for playtester feedback. `--only gallery|buildings`, `--width`, `--height`, `--samples`.

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
  config.py      config -> resolved specs; materials, pitches, relief
  spec.py        WallSpec / RoofSpec / MaterialSpec, validation
  ids.py         regeneration-stable prefab ids
  textures.py    texture map discovery
  manifest.py    the library catalogue
  cli.py         plan / build / textures / showcase
  blender/       runs INSIDE Blender:
    run.py         entry point: build specs, render, export
    build.py       wall geometry (bmesh)
    roof.py        roof geometry: slab, ridge, hip, valley, caps
    materials.py   Principled BSDF from texture maps
    relief.py      real geometric relief from a height map
    thumbnail.py   per-prefab preview renders
    showcase.py    gallery / sample-building layout helpers
    showcase_run.py  entry point for the showcase renders
    export.py      .blend / .glb / .fbx writers
```

## Things worth knowing

**Mating planes are exact.** Everything a neighbouring module touches stays perfectly
planar: wall side faces, roof plumb cuts, and — for displaced surfaces — a feathered
band where relief ramps to zero. Alignment is exact by construction, not by tolerance.

**Prefab ids are stable across regeneration.** Creator-authored levels reference them, so
ids derive from the *semantic* axis values with numerics normalised to integer
millimetres (`wall.2000x2500x200.door.brick`), never from the filename or display name.
Renaming a prefab does not break a level. Duplicate ids are a hard error.

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
pip install pytest              # not currently installed
python3 -m pytest tests -q      # 40 tests
```

Covers matrix expansion, exclude rules, stable ids, texture discovery across naming
conventions, relief config, and manifest shape. Geometry is verified separately by
building and measuring the meshes (manifold, volumes, mating-plane drift).

## Known gaps

- **No corner post.** Four equal-length walls meeting at a corner put coplanar faces
  against each other, which z-fights. A corner/quoin piece is the obvious next part type.
- **Relief does not apply to roof pieces yet** — it warns and leaves them flat.
- **Builds are always full rebuilds**; there is no incremental caching.
- Hip and valley trim caps overhang their footprint, so they do not bound to a grid cell
  the way slabs and corners do.
