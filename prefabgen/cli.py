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

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender", "run.py")

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
    args = parser.parse_args(argv)
    return args.func(args)
