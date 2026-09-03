"""Command line front end. Runs OUTSIDE Blender - stdlib + pyyaml only.

    python3 -m prefabgen plan  config/walls.yaml
    python3 -m prefabgen build config/walls.yaml
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import config as config_mod
from . import manifest as manifest_mod
from .spec import MAP_ROLES

_BLENDER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender")
RUNNER = os.path.join(_BLENDER_DIR, "run.py")
SHOWCASE_RUNNER = os.path.join(_BLENDER_DIR, "showcase_run.py")

BLENDER_CANDIDATES = [
    "/Applications/Blender.app/Contents/MacOS/Blender",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    "/usr/bin/blender",
]


def find_blender(explicit=None) -> str:
    for candidate in [explicit, os.environ.get("BLENDER"), shutil.which("blender")] + BLENDER_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
        if candidate and shutil.which(candidate):
            return shutil.which(candidate)
    raise SystemExit("could not find Blender - set $BLENDER or pass --blender")


def build_plan(args):
    cfg = config_mod.load(args.config)
    plan = config_mod.resolve(cfg, base_dir=os.path.dirname(os.path.abspath(args.config)) or ".")
    if args.filter:
        plan.specs = [s for s in plan.specs if fnmatch.fnmatch(s.name, args.filter)
                      or fnmatch.fnmatch(s.id, args.filter)]
    if getattr(args, "no_thumbnails", False):
        plan.thumbnails.enabled = False
    return plan


def _describe(spec) -> str:
    if spec.type == "gable":
        return f"{spec.width}m {spec.shape}, apex {spec.apex:.3f}m @{spec.pitch}"
    if spec.type == "corner":
        return f"{spec.arm}m arms x {spec.height}m, {spec.thickness}m thick"
    if spec.type in ("door", "window"):
        variant = spec.leaf or spec.pattern or "fixed"
        moving = spec.animation.kind if spec.animation.kind != "none" else "static"
        return (f"fits {spec.fits} {spec.opening.width}x{spec.opening.height}m, "
                f"clear {spec.clear_width:.3f}x{spec.clear_height:.3f}m, {variant}, {moving}")
    if spec.type == "roof":
        return (f"{spec.span}x{spec.run}m run, rise {spec.rise:.3f}m, "
                f"slope {spec.slope_length:.3f}m @{spec.angle}deg")
    openings = ", ".join(o.kind for o in spec.openings) or "solid"
    return f"{spec.width}x{spec.height}x{spec.thickness}m [{openings}]"


def _texture_warnings(plan):
    lines = list(f"  {w}" for w in plan.warnings)
    for name, m in sorted(plan.materials.items()):
        if not m.maps:
            lines.append(f"  {name}: no textures found in {m.search_dir} "
                         f"(falling back to flat colour)")
            continue
        missing = m.missing_maps()
        if missing:
            lines.append(f"  {name}: {', '.join(missing)} map file(s) listed in config "
                         f"do not exist")
        absent = [r for r in ("albedo", "normal", "roughness") if r not in m.maps]
        if absent:
            lines.append(f"  {name}: no {', '.join(absent)} map found in {m.search_dir}")
    return lines


def cmd_textures(args) -> int:
    """Show what the texture scan resolved for each material."""
    plan = build_plan(args)
    for name, m in sorted(plan.materials.items()):
        flag = "  [DirectX normal - green channel inverted]" if m.normal_flip_green else ""
        print(f"{name}  (tile_size {m.tile_size}m){flag}")
        if m.relief:
            print(f"  relief:   strength {m.relief.strength}m, resolution "
                  f"{m.relief.resolution}m, feather {m.relief.feather}m "
                  f"(driven by the height map below)")
        print(f"  searched: {m.search_dir}")
        if not m.maps:
            print("  nothing found - using flat base_color")
        for role in MAP_ROLES:
            if role in m.maps:
                mark = "" if os.path.exists(m.maps[role]) else "   <- MISSING"
                print(f"  {role:<10} {os.path.relpath(m.maps[role], m.search_dir)}{mark}")
        print()
    for w in plan.warnings:
        print(f"warning: {w}")
    return 0


def cmd_plan(args) -> int:
    plan = build_plan(args)
    for spec in plan.specs:
        print(f"  {spec.id:<44} {_describe(spec)} {spec.material.name}")
    for s in plan.skipped:
        print(f"  skipped {s.name:<26} {s.reason}")

    warnings = _texture_warnings(plan)
    if warnings:
        print("\ntextures not found yet:")
        print("\n".join(warnings))
    print(f"\n{len(plan.specs)} prefab(s), {len(plan.skipped)} skipped, "
          f"{len(plan.materials)} material(s) -> {plan.out_dir} as {', '.join(plan.formats)}"
          f"{' + thumbnails' if plan.thumbnails.enabled else ''}")
    return 0


def cmd_build(args) -> int:
    plan = build_plan(args)
    if not plan.specs:
        print("nothing to build")
        return 1
    for s in plan.skipped:
        print(f"skipped {s.name}: {s.reason}", file=sys.stderr)
    for line in _texture_warnings(plan):
        print(f"warning:{line}", file=sys.stderr)

    blender = find_blender(args.blender)
    out_dir = os.path.abspath(plan.out_dir)
    report_path = os.path.join(tempfile.gettempdir(), "prefabgen_report.json")
    job = {
        "models_dir": os.path.join(out_dir, plan.models_dir),
        "thumbnails_dir": os.path.join(out_dir, plan.thumbnails_dir),
        "formats": plan.formats,
        "pack_textures": plan.pack_textures,
        "thumbnails": {"enabled": plan.thumbnails.enabled, "size": plan.thumbnails.size,
                       "samples": plan.thumbnails.samples},
        "report_path": report_path,
        "specs": [s.to_dict() for s in plan.specs],
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(job, fh)
        job_path = fh.name
    try:
        cmd = [blender, "--background", "--factory-startup", "--python", RUNNER, "--", "--job", job_path]
        proc = subprocess.run(cmd, capture_output=not args.verbose, text=True)
        if proc.returncode != 0:
            print(proc.stdout or "", file=sys.stderr)
            print(proc.stderr or "", file=sys.stderr)
            return proc.returncode
        if not args.verbose:
            for line in (proc.stdout or "").splitlines():
                if line.startswith("[prefabgen]"):
                    print(line)
    finally:
        os.unlink(job_path)

    # Blender exits 0 even when a --python script raises, so a missing report is the
    # only reliable signal that the build actually failed.
    if not os.path.exists(report_path):
        print("blender did not produce a build report - the run failed", file=sys.stderr)
        if not args.verbose:
            print(proc.stdout or "", file=sys.stderr)
            print(proc.stderr or "", file=sys.stderr)
            print("re-run with --verbose for the full log", file=sys.stderr)
        return 1
    with open(report_path) as fh:
        report = json.load(fh)
    os.unlink(report_path)

    path = manifest_mod.write(manifest_mod.compose(plan, report),
                              os.path.join(out_dir, plan.manifest))
    print(f"[prefabgen] manifest -> {path}")
    return 0


def cmd_showcase(args) -> int:
    """Render a gallery of every piece and a few assembled sample buildings."""
    specs, out_dir = [], None
    for path in args.configs:
        cfg = config_mod.load(path)
        plan = config_mod.resolve(cfg, base_dir=os.path.dirname(os.path.abspath(path)) or ".")
        specs.extend(plan.specs)
        out_dir = out_dir or os.path.abspath(plan.out_dir)
    if not specs:
        print("no prefabs to show", file=sys.stderr)
        return 1

    target = os.path.abspath(args.out) if args.out else out_dir
    job = {
        "specs": [s.to_dict() for s in specs],
        "gallery": os.path.join(target, "gallery.png") if args.only in (None, "gallery") else None,
        "buildings": os.path.join(target, "buildings.png") if args.only in (None, "buildings") else None,
        "hero": os.path.join(target, "hero.png") if args.only in (None, "hero") else None,
        "width": args.width, "height": args.height, "samples": args.samples,
        "hero_width": args.hero_width, "hero_height": args.hero_height,
        "hero_samples": args.hero_samples,
        "hero_wall": args.hero_wall, "hero_roof": args.hero_roof,
        "hero_joinery": args.hero_joinery, "hero_leaf": args.hero_leaf,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(job, fh)
        job_path = fh.name
    try:
        cmd = [find_blender(args.blender), "--background", "--factory-startup",
               "--python", SHOWCASE_RUNNER, "--", "--job", job_path]
        proc = subprocess.run(cmd, capture_output=not args.verbose, text=True)
        if proc.returncode != 0 or (not args.verbose and "[prefabgen]" not in (proc.stdout or "")):
            print(proc.stdout or "", file=sys.stderr)
            print(proc.stderr or "", file=sys.stderr)
            return proc.returncode or 1
        for line in (proc.stdout or "").splitlines():
            if line.startswith("[prefabgen]") or line.startswith(("GALLERY", "BUILDINGS")):
                print(line)
    finally:
        os.unlink(job_path)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="prefabgen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("build", cmd_build), ("textures", cmd_textures)):
        p = sub.add_parser(name)
        p.add_argument("config")
        p.add_argument("--filter", help="glob over prefab names or ids, e.g. 'wall_4x*brick'")
        p.add_argument("--blender", help="path to the Blender executable")
        p.add_argument("--no-thumbnails", action="store_true", help="skip preview renders")
        p.add_argument("--verbose", action="store_true", help="stream Blender's full output")
        p.set_defaults(func=fn)
    show = sub.add_parser("showcase")
    show.add_argument("configs", nargs="+", help="one or more config files to pool")
    show.add_argument("--out", help="directory for gallery.png / buildings.png")
    show.add_argument("--only", choices=["gallery", "buildings", "hero"],
                      help="render just one")
    show.add_argument("--width", type=int, default=3200)
    show.add_argument("--height", type=int, default=1800)
    show.add_argument("--samples", type=int, default=96)
    show.add_argument("--hero-width", type=int, default=2800)
    show.add_argument("--hero-height", type=int, default=2000)
    show.add_argument("--hero-samples", type=int, default=192,
                      help="hero shot is one close-up image, so it can afford more")
    show.add_argument("--hero-wall", default="brown_planks", help="wall material for the hero shot")
    show.add_argument("--hero-roof", default="shingle_ceramic", help="roof material for the hero shot")
    show.add_argument("--hero-joinery", default="oak", help="door/window material for the hero shot")
    show.add_argument("--hero-leaf", default="banded", help="door leaf style for the hero shot")
    show.add_argument("--blender", help="path to the Blender executable")
    show.add_argument("--verbose", action="store_true")
    show.set_defaults(func=cmd_showcase)

    args = parser.parse_args(argv)
    return args.func(args)
