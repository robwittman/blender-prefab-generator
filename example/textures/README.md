# Textures

Unzip a texture set into the folder named after its material and the generator finds
it — no config needed:

    textures/brick/Bricks075A_2K-JPG_Color.jpg
    textures/brick/Bricks075A_2K-JPG_NormalGL.jpg
    textures/brick/Bricks075A_2K-JPG_Roughness.jpg

Files are matched to roles by their **trailing token**, so ambientCG / cc0-textures
downloads work as they come out of the zip, and so do plain names:

| role      | recognised endings                                           |
|-----------|--------------------------------------------------------------|
| albedo    | `Color`, `Colour`, `Albedo`, `BaseColor`, `Diffuse`, `Col`    |
| normal    | `NormalGL`, `Normal`, `Nrm`, `Nor` (and `NormalDX`, see below) |
| roughness | `Roughness`, `Rough`, `Rgh`                                  |
| metallic  | `Metallic`, `Metalness`, `Metal`                             |
| ao        | `AmbientOcclusion`, `Occlusion`, `AO`                        |
| height    | `Displacement`, `Disp`, `Height`, `Hgt`                      |

Any image format works (`.png .jpg .jpeg .tga .tif .exr .webp`). Leaving the zip's
own subfolder in place is fine — the scan recurses. Every role is optional; a material
with no textures at all falls back to its flat `base_color`, so the kit always builds.

The height map is not wired into the shader — it drives real geometry at build time
(see **Relief** below) and is not embedded in the shipped prefab.

Check what was resolved:

    python3 -m prefabgen textures config/walls.yaml

## NormalGL vs NormalDX

ambientCG ships both. Blender needs the **OpenGL** convention, so `NormalGL` is
preferred automatically. If only a `NormalDX` file is present it is still used, with
its green channel inverted in the shader — using a DirectX map unflipped lights every
surface from the wrong direction, which is easy to miss and looks subtly wrong
everywhere. `normal_flip_green: true` forces the flip if a file is misnamed.

## Overrides

When the scan guesses wrong, override per material in `config/walls.yaml`:

    brick:
      dir: Bricks075A_2K-JPG       # folder name differs from the material name
      maps:
        albedo: Bricks075A_2K-JPG_Color.jpg
        ao: null                   # ignore a map that was found
      normal_flip_green: true

Explicit entries win; unlisted roles still auto-resolve. Paths may be relative to the
material folder, relative to `textures/`, or absolute.

## Choosing textures

Use **seamlessly tiling** sets — meshes are UV-mapped in world metres and the material
repeats every `tile_size` metres, so a non-tiling texture shows visible seams across a
4m wall. 1K or 2K is plenty at this scale.

Sources: [ambientCG](https://ambientcg.com) and
[Poly Haven](https://polyhaven.com/textures), both CC0.

Licensing note: whatever goes in here is inherited by everything creators build with
the library, so prefer CC0 over anything with attribution or share-alike terms.

## Relief (real geometric depth)

A normal map cannot change a silhouette, so a flat wall reads as printed texture at
grazing angles. Opt a material into real displaced geometry:

    brown_planks:
      dir: planks_brown
      relief:
        strength: 0.03      # metres of displacement at full white
        resolution: 0.05    # metres per grid cell - drives fidelity and vertex count
        feather: 0.06       # relief ramps to flat this far from any mating plane

`relief: true` accepts all defaults. It requires a height map; asking for it without
one warns and leaves the surface flat rather than failing the build.

**Why `feather` exists.** Naive displacement moves the module's *edges*: border
vertices have 45-degree blended normals, so they travel sideways off the mating plane —
measured at 12mm of drift on a 2m wall, which shows up as visible cracks along every
join between neighbouring pieces. The mask ramps displacement to zero at every surface
a neighbour touches (left/right mating planes, floor, ceiling, opening reveals), so
those vertices do not move at all and alignment is exact by construction. The cost is
that relief flattens out within `feather` metres of an edge.

**`resolution` is metres per grid cell**, and it is what keeps relief consistent. The
grid is laid down at build time rather than by subdividing the finished mesh, because
subdivision gives every face the same cut count regardless of its size - which sampled
a 4m wall ten times more coarsely than a 1m one and turned the same material into
visibly different depths across the kit.

**Vertex cost is the real tradeoff**, and it is why relief is per-material. Counts now
scale with surface area, as they should:

| wall (2x2.5m) | flat | relief @ 0.05 |
|---------------|------|---------------|
| solid         | 8    | 4,182         |
| with window   | 32   | 3,124         |
| solid 4x4m    | 8    | 13,122        |

Halving `resolution` roughly quadruples the count. Leave relief off for materials that
are genuinely flat (plaster, concrete). Every prefab's vertex count is in
`manifest.json` so the budget stays visible.

**Tuning depth.** `strength` is metres of displacement at full white; the default 0.03
is subtle at a distance. Note the `feather` band is flat by construction, so relief
never shows in the outermost silhouette - it reads as shading on the face. For
pronounced board or brick depth try `strength: 0.09` with `feather: 0.03`.
