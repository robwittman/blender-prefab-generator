"""Entry point executed inside Blender:

    blender --background --factory-startup --python run.py -- --job job.json

Reads resolved specs as JSON, builds each in a clean scene, writes the requested
formats and an optional thumbnail, then emits a build report the CLI turns into the
library manifest. Knows nothing about the matrix or the config file.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

import bpy  # noqa: E402

from prefabgen.blender import build as build_mod          # noqa: E402
from prefabgen.blender import export as export_mod        # noqa: E402
from prefabgen.blender import materials as materials_mod  # noqa: E402
from prefabgen.blender import relief as relief_mod        # noqa: E402
from prefabgen.blender import roof as roof_mod            # noqa: E402
from prefabgen.blender import thumbnail as thumb_mod      # noqa: E402
from prefabgen.spec import spec_from_dict                 # noqa: E402


def main(argv):
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    with open(_arg(args, "--job")) as fh:
        job = json.load(fh)

    models_dir = job["models_dir"]
    thumbs_dir = job["thumbnails_dir"]
    thumbs_on = job["thumbnails"]["enabled"]
    os.makedirs(models_dir, exist_ok=True)
    if thumbs_on:
        os.makedirs(thumbs_dir, exist_ok=True)

    report = {"prefabs": [], "missing_textures": []}

    for raw in job["specs"]:
        spec = spec_from_dict(raw)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.scale_length = 1.0

        builder = roof_mod.build if spec.type == "roof" else build_mod.build
        obj = builder(spec, report)
        bpy.context.collection.objects.link(obj)
        stats = relief_mod.apply(obj, spec, report)

        entry = {"id": spec.id, "files": {}, "relief": stats,
                 "vertices": len(obj.data.vertices)}

        if thumbs_on:
            cam = thumb_mod.setup(job["thumbnails"]["size"], job["thumbnails"]["samples"])
            thumb_mod.frame(cam, obj)
            path = os.path.join(thumbs_dir, spec.name + ".png")
            thumb_mod.render(path)
            entry["files"]["thumbnail"] = path
            # The camera and lights must not end up inside the shipped prefab.
            for helper in [o for o in scene.objects if o is not obj]:
                bpy.data.objects.remove(helper, do_unlink=True)

        # Non-.blend formats must be written while image paths are still absolute:
        # save_as_mainfile(copy=True) never sets bpy.data.filepath, so blend-relative
        # "//" paths would not resolve and the exporter would silently drop textures.
        stem = os.path.join(models_dir, spec.name)
        for fmt in [f for f in job["formats"] if f != "blend"]:
            # `pack_textures` reached the .blend branch below and nothing else, so every glTF and
            # FBX embedded a private copy of every texture whatever the config said.
            entry["files"][fmt] = export_mod.write(fmt, stem, job["pack_textures"])

        if "blend" in job["formats"]:
            if job["pack_textures"]:
                materials_mod.pack_all()
            else:
                materials_mod.relativize(models_dir)
            entry["files"]["blend"] = export_mod.write("blend", stem)
        report["prefabs"].append(entry)
        print(f"[prefabgen] {spec.id}")

    with open(job["report_path"], "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"[prefabgen] done: {len(report['prefabs'])} prefab(s)")


def _arg(args, flag):
    if flag not in args:
        raise SystemExit(f"{flag} is required")
    return args[args.index(flag) + 1]


main(sys.argv)
