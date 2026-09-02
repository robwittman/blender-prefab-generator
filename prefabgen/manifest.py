"""The library catalogue an asset picker reads.

Composed outside Blender so the schema stays unit-testable. Paths are relative to
the output directory and entries are sorted by id, so regenerating an unchanged
library produces a byte-identical manifest (no timestamps) and diffs stay readable.
"""
from __future__ import annotations

import json
import os

SCHEMA_VERSION = 1


def compose(plan, report: dict) -> dict:
    written = {e["id"]: e.get("files", {}) for e in report.get("prefabs", [])}
    stats = {e["id"]: e for e in report.get("prefabs", [])}

    prefabs = []
    for spec in plan.specs:
        files = {k: _rel(v, plan.out_dir) for k, v in written.get(spec.id, {}).items()}
        prefabs.append({
            "id": spec.id,
            "name": spec.name,
            "display_name": spec.display_name,
            "type": spec.type,
            "category": spec.category,
            "tags": sorted(set(spec.tags)),
            "dimensions": spec.dimensions(),
            "origin": spec.origin,
            "material": spec.material.name,
            "openings": [o.to_dict() for o in getattr(spec, "openings", ())],
            "piece": getattr(spec, "piece", None),
            "vertices": stats.get(spec.id, {}).get("vertices"),
            "relief": stats.get(spec.id, {}).get("relief"),
            "files": files,
        })
    prefabs.sort(key=lambda p: p["id"])

    used = {s.material.name for s in plan.specs}
    materials = [{"id": m.name, "display_name": m.display_name, "tile_size": m.tile_size,
                  "maps": {r: _rel(p, plan.out_dir) for r, p in sorted(m.maps.items())}}
                 for name, m in sorted(plan.materials.items()) if name in used]

    return {
        "schema_version": SCHEMA_VERSION,
        "library": plan.library,
        "counts": {"prefabs": len(prefabs), "materials": len(materials)},
        "materials": materials,
        "prefabs": prefabs,
    }


def write(manifest: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=False)
        fh.write("\n")
    return path


def _rel(path: str, start: str) -> str:
    try:
        return os.path.relpath(path, start).replace(os.sep, "/")
    except ValueError:
        return path
