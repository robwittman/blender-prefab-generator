"""Incremental builds: deciding what actually has to be built again.

A prefab's output is a pure function of three things - its resolved spec, the bytes of
every texture that spec names, and the Blender-side code that turns one into the other.
Hash all three, and a prefab whose hash is unchanged and whose files are still on disk
does not need building again. Nothing here imports ``bpy``: the decision is made
outside Blender, and Blender is handed only the specs that survived it.

The cache also remembers each prefab's build *report entry*, and that is what makes a
partial build safe rather than destructive. The manifest is composed from the whole
plan, so an entry for a prefab this run did not touch has to come from somewhere -
without it, editing one material would quietly drop the other 140 prefabs out of the
catalogue, which is worse than the full rebuild it replaced.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

CACHE_VERSION = 1
CACHE_NAME = ".prefabgen-cache.json"
_CHUNK = 1 << 20


def builder_digest() -> str:
    """Hash of the Blender-side source.

    A spec records what to build, never how, so a change to the geometry or material
    code is invisible to every other input. Without this, editing build.py and
    rebuilding would reuse output produced by the previous version of it.
    """
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender")
    h = hashlib.sha256()
    for name in sorted(os.listdir(here)):
        if name.endswith(".py"):
            h.update(name.encode())
            with open(os.path.join(here, name), "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def texture_paths(spec_dict: dict) -> list:
    """Every texture file a spec references.

    Walks the dict rather than reading ``spec.material.maps``, because a door carries a
    material per slot and a wall can carry a separate reveal material - a prefab that
    depends on a texture it does not name in the obvious place would silently stop
    rebuilding when that texture changed.
    """
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if key == "maps" and isinstance(val, dict):
                    found.extend(p for p in val.values() if isinstance(p, str))
                else:
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(spec_dict)
    return sorted(set(found))


@dataclass
class Split:
    """The plan, divided by what the cache says."""
    todo: list = field(default_factory=list)      # specs Blender must build
    reused: list = field(default_factory=list)    # specs whose cached output stands
    keys: dict = field(default_factory=dict)      # id -> cache key, to record on success
    reasons: dict = field(default_factory=dict)   # id -> why it is being rebuilt


def split(specs, cache, formats, pack_textures, thumbnails, builder=None) -> Split:
    builder = builder or builder_digest()
    out = Split()
    for spec in specs:
        out.keys[spec.id] = key = cache.key(spec.to_dict(), formats, pack_textures, builder)
        reason = cache.stale(spec, key, thumbnails)
        if reason:
            out.reasons[spec.id] = reason
            out.todo.append(spec)
        else:
            out.reused.append(spec)
    return out


def merged_report(report: dict, cache: "Cache", specs) -> dict:
    """A report covering `specs`, filled in from the cache for whatever was not built.

    The manifest is composed from the whole plan. A run that builds twelve prefabs
    produces a report describing twelve, so without this the other hundred and thirty
    would vanish from the catalogue - the incremental build would be silently
    destructive in a way the full rebuild never was.
    """
    built = {e["id"] for e in report.get("prefabs", [])}
    prefabs = list(report.get("prefabs", []))
    for spec in specs:
        if spec.id in built:
            continue
        entry = cache.entry(spec.id)
        if entry:
            prefabs.append(entry)
    return dict(report, prefabs=prefabs)


class Cache:
    """Build state for one output directory, stored beside the models it describes."""

    def __init__(self, path: str, data: dict = None):
        data = data or {}
        current = data.get("version") == CACHE_VERSION
        self.path = path
        self.prefabs = data.get("prefabs", {}) if current else {}
        self.digests = data.get("digests", {}) if current else {}

    @classmethod
    def load(cls, out_dir: str) -> "Cache":
        path = os.path.join(out_dir, CACHE_NAME)
        try:
            with open(path) as fh:
                return cls(path, json.load(fh))
        except (OSError, ValueError):
            # A missing or corrupt cache is not an error - it just means a full build.
            return cls(path)

    @classmethod
    def empty(cls, out_dir: str) -> "Cache":
        """A cache that knows nothing, but still records what this build produces."""
        return cls(os.path.join(out_dir, CACHE_NAME))

    def save(self) -> str:
        self.digests = {p: d for p, d in self.digests.items() if os.path.exists(p)}
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump({"version": CACHE_VERSION, "prefabs": self.prefabs,
                       "digests": self.digests}, fh, indent=2, sort_keys=True)
            fh.write("\n")
        return self.path

    # --- hashing ------------------------------------------------------------

    def digest(self, path: str) -> str:
        """Content hash of a texture, re-read only when its size or mtime moved.

        Content rather than the timestamp alone because a restored file - a checkout, a
        copy, a sync - keeps its bytes and changes its stamp, and rebuilding a whole kit
        for that is exactly the false alarm that makes people pass --no-cache forever.
        Re-reading only on a stamp change keeps a 4K texture set from being hashed on
        every build.
        """
        try:
            st = os.stat(path)
        except OSError:
            return ""            # a missing texture is the build's warning to make
        stamp = [st.st_size, st.st_mtime_ns]
        known = self.digests.get(path)
        if known and known.get("stamp") == stamp:
            return known["digest"]
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                h.update(chunk)
        self.digests[path] = {"stamp": stamp, "digest": h.hexdigest()}
        return self.digests[path]["digest"]

    def key(self, spec_dict: dict, formats, pack_textures, builder: str) -> str:
        h = hashlib.sha256()
        h.update(json.dumps(spec_dict, sort_keys=True).encode())
        h.update(json.dumps([sorted(formats), bool(pack_textures), builder]).encode())
        for path in texture_paths(spec_dict):
            h.update(path.encode())
            h.update(self.digest(path).encode())
        return h.hexdigest()

    # --- what the cache knows -----------------------------------------------

    def stale(self, spec, key: str, thumbnails):
        """Why this prefab has to be built again, or None if it does not.

        Thumbnail settings are deliberately NOT part of the key. Iterating with
        --no-thumbnails and then doing one full build is the documented workflow, and
        folding the thumbnail size into the key would make that last build a full
        rebuild of geometry that had not changed. A missing thumbnail is caught here
        instead, and only when thumbnails are actually wanted.
        """
        rec = self.prefabs.get(spec.id)
        if rec is None:
            return "not built yet"
        if rec.get("key") != key:
            return "spec, textures or builder changed"
        files = (rec.get("entry") or {}).get("files") or {}
        if not any(fmt != "thumbnail" for fmt in files):
            return "no model was written"
        for fmt, path in sorted(files.items()):
            if fmt != "thumbnail" and not os.path.exists(path):
                return f"the {fmt} output is missing"
        if thumbnails.enabled:
            thumb = files.get("thumbnail")
            if not thumb or not os.path.exists(thumb):
                return "the thumbnail is missing"
            if rec.get("thumbnails") != [thumbnails.size, thumbnails.samples]:
                return "thumbnail settings changed"
        return None

    def entry(self, spec_id: str):
        rec = self.prefabs.get(spec_id)
        return dict(rec["entry"]) if rec and rec.get("entry") else None

    def record(self, spec_id: str, key: str, entry: dict, thumbnails) -> None:
        self.prefabs[spec_id] = {
            "key": key, "entry": entry,
            "thumbnails": [thumbnails.size, thumbnails.samples] if thumbnails.enabled else None,
        }

    def orphans(self, live_ids) -> list:
        """Prefabs the cache has built that the config no longer produces."""
        return sorted(set(self.prefabs) - set(live_ids))

    def forget(self, spec_ids) -> None:
        for spec_id in spec_ids:
            self.prefabs.pop(spec_id, None)
