"""What the incremental build decides to rebuild.

None of this needs Blender: the decision is made from the resolved specs, the texture
files on disk and the builder source, all of which are readable outside it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prefabgen import cache as cache_mod
from prefabgen.cache import Cache, merged_report, split, texture_paths
from prefabgen.config import Thumbnails, resolve
from prefabgen.manifest import compose

THUMBS = Thumbnails(enabled=True, size=512, samples=48)
NO_THUMBS = Thumbnails(enabled=False)
BUILDER = "builder-v1"


def _kit(tmp_path, materials=("planks",), widths=(2,)):
    """A resolved plan whose materials have real texture files on disk."""
    for name in materials:
        folder = tmp_path / "textures" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}_diff_4k.jpg").write_bytes(b"albedo bytes")
        (folder / f"{name}_disp_4k.jpg").write_bytes(b"height bytes")
    cfg = {
        "output": {"dir": "build"},
        "textures": {"root": "textures"},
        "materials": {name: {} for name in materials},
        "parts": [{"type": "wall", "name": "wall_{width}_{material}",
                   "matrix": {"width": list(widths), "height": [2.5],
                              "material": sorted(materials)}}],
    }
    return resolve(cfg, base_dir=str(tmp_path))


def _built(tmp_path, spec, thumbnail=True):
    """The report entry Blender would emit, with the files actually written."""
    models = tmp_path / "build" / "models"
    models.mkdir(parents=True, exist_ok=True)
    blend = models / (spec.name + ".blend")
    blend.write_bytes(b"model")
    files = {"blend": str(blend)}
    if thumbnail:
        thumbs = tmp_path / "build" / "thumbnails"
        thumbs.mkdir(parents=True, exist_ok=True)
        thumb = thumbs / (spec.name + ".png")
        thumb.write_bytes(b"png")
        files["thumbnail"] = str(thumb)
    return {"id": spec.id, "files": files, "vertices": 8, "parts": None, "relief": None}


def _cache_with(tmp_path, plan, thumbnails=THUMBS, thumbnail=True):
    """A cache in the state a completed build would leave it."""
    cache = Cache.empty(str(tmp_path / "build"))
    for spec in plan.specs:
        key = cache.key(spec.to_dict(), plan.formats, plan.pack_textures, BUILDER)
        cache.record(spec.id, key, _built(tmp_path, spec, thumbnail), thumbnails)
    return cache


# --- what goes into the key -------------------------------------------------

def test_the_same_inputs_give_the_same_key(tmp_path):
    plan = _kit(tmp_path)
    cache = Cache.empty(str(tmp_path / "build"))
    spec = plan.specs[0].to_dict()
    assert (cache.key(spec, ["blend"], False, BUILDER)
            == cache.key(spec, ["blend"], False, BUILDER))


def test_a_changed_spec_changes_the_key(tmp_path):
    plan = _kit(tmp_path, widths=(2, 4))
    cache = Cache.empty(str(tmp_path / "build"))
    keys = {cache.key(s.to_dict(), ["blend"], False, BUILDER) for s in plan.specs}
    assert len(keys) == len(plan.specs)


def test_editing_a_texture_changes_the_key_of_everything_using_it(tmp_path):
    """The whole point: touch one material, rebuild only what that material reaches."""
    plan = _kit(tmp_path, materials=("planks", "brick"))
    cache = Cache.empty(str(tmp_path / "build"))
    before = {s.id: cache.key(s.to_dict(), ["blend"], False, BUILDER) for s in plan.specs}

    (tmp_path / "textures" / "planks" / "planks_diff_4k.jpg").write_bytes(b"repainted")
    after = {s.id: cache.key(s.to_dict(), ["blend"], False, BUILDER) for s in plan.specs}

    changed = [i for i in before if before[i] != after[i]]
    assert changed == [i for i in before if "planks" in i]


def test_a_changed_builder_changes_every_key(tmp_path):
    plan = _kit(tmp_path)
    cache = Cache.empty(str(tmp_path / "build"))
    spec = plan.specs[0].to_dict()
    assert (cache.key(spec, ["blend"], False, "builder-v1")
            != cache.key(spec, ["blend"], False, "builder-v2"))


def test_the_output_format_is_part_of_the_key(tmp_path):
    plan = _kit(tmp_path)
    cache = Cache.empty(str(tmp_path / "build"))
    spec = plan.specs[0].to_dict()
    assert (cache.key(spec, ["blend"], False, BUILDER)
            != cache.key(spec, ["blend", "glb"], False, BUILDER))
    assert (cache.key(spec, ["glb"], False, BUILDER)
            != cache.key(spec, ["glb"], True, BUILDER))


def test_the_real_builder_digest_covers_the_blender_source():
    assert len(cache_mod.builder_digest()) == 64


def test_texture_paths_finds_maps_below_the_top_level():
    """A door carries a material per slot, not one material."""
    spec = {"slots": {"frame": {"maps": {"albedo": "/t/oak.jpg"}},
                      "glass": {"maps": {"albedo": "/t/glass.jpg"}}},
            "material": {"maps": {"normal": "/t/oak_n.jpg"}}}
    assert texture_paths(spec) == ["/t/glass.jpg", "/t/oak.jpg", "/t/oak_n.jpg"]


def test_a_missing_texture_does_not_break_the_key(tmp_path):
    cache = Cache.empty(str(tmp_path / "build"))
    spec = {"material": {"maps": {"albedo": str(tmp_path / "gone.jpg")}}}
    assert cache.key(spec, ["blend"], False, BUILDER)


# --- hashing cost -----------------------------------------------------------

def test_an_unchanged_file_is_not_read_again(tmp_path):
    """Proven by poisoning the stored digest: a re-read would overwrite it."""
    path = tmp_path / "tex.jpg"
    path.write_bytes(b"bytes")
    cache = Cache.empty(str(tmp_path / "build"))
    cache.digest(str(path))
    cache.digests[str(path)]["digest"] = "poisoned"
    assert cache.digest(str(path)) == "poisoned"


def test_a_rewritten_file_is_read_again(tmp_path):
    path = tmp_path / "tex.jpg"
    path.write_bytes(b"bytes")
    cache = Cache.empty(str(tmp_path / "build"))
    cache.digest(str(path))
    cache.digests[str(path)]["digest"] = "poisoned"
    path.write_bytes(b"different bytes")          # size moves, so the stamp does
    assert cache.digest(str(path)) != "poisoned"


# --- staleness --------------------------------------------------------------

def test_a_completed_build_is_entirely_reusable(tmp_path):
    plan = _kit(tmp_path, widths=(1, 2, 4))
    cache = _cache_with(tmp_path, plan)
    result = split(plan.specs, cache, plan.formats, plan.pack_textures, THUMBS, BUILDER)
    assert result.todo == [] and len(result.reused) == 3


def test_an_unknown_prefab_is_built(tmp_path):
    plan = _kit(tmp_path)
    cache = Cache.empty(str(tmp_path / "build"))
    assert cache.stale(plan.specs[0], "any-key", THUMBS) == "not built yet"


def test_a_deleted_model_is_rebuilt(tmp_path):
    plan = _kit(tmp_path)
    cache = _cache_with(tmp_path, plan)
    spec = plan.specs[0]
    os.unlink(cache.entry(spec.id)["files"]["blend"])
    key = cache.key(spec.to_dict(), plan.formats, plan.pack_textures, BUILDER)
    assert cache.stale(spec, key, THUMBS) == "the blend output is missing"


def test_a_changed_key_is_rebuilt(tmp_path):
    plan = _kit(tmp_path)
    cache = _cache_with(tmp_path, plan)
    assert cache.stale(plan.specs[0], "some-other-key", THUMBS) == \
        "spec, textures or builder changed"


def test_a_missing_thumbnail_is_rebuilt_only_when_thumbnails_are_wanted(tmp_path):
    """The documented workflow is to iterate with --no-thumbnails, then build once."""
    plan = _kit(tmp_path)
    cache = _cache_with(tmp_path, plan, thumbnails=NO_THUMBS, thumbnail=False)
    spec = plan.specs[0]
    key = cache.key(spec.to_dict(), plan.formats, plan.pack_textures, BUILDER)
    assert cache.stale(spec, key, NO_THUMBS) is None
    assert cache.stale(spec, key, THUMBS) == "the thumbnail is missing"


def test_resizing_thumbnails_rebuilds(tmp_path):
    plan = _kit(tmp_path)
    cache = _cache_with(tmp_path, plan)
    spec = plan.specs[0]
    key = cache.key(spec.to_dict(), plan.formats, plan.pack_textures, BUILDER)
    assert cache.stale(spec, key, THUMBS) is None
    assert cache.stale(spec, key, Thumbnails(True, 1024, 48)) == "thumbnail settings changed"


def test_thumbnail_settings_do_not_invalidate_geometry(tmp_path):
    """Turning thumbnails off must not make the next full build a full rebuild."""
    plan = _kit(tmp_path)
    cache = Cache.empty(str(tmp_path / "build"))
    spec = plan.specs[0].to_dict()
    assert (cache.key(spec, ["blend"], False, BUILDER)
            == cache.key(spec, ["blend"], False, BUILDER))


def test_editing_one_material_rebuilds_only_its_prefabs(tmp_path):
    plan = _kit(tmp_path, materials=("planks", "brick"), widths=(1, 2, 4))
    cache = _cache_with(tmp_path, plan)
    (tmp_path / "textures" / "planks" / "planks_disp_4k.jpg").write_bytes(b"new height")

    result = split(plan.specs, cache, plan.formats, plan.pack_textures, THUMBS, BUILDER)
    assert len(plan.specs) == 6
    assert sorted(s.material.name for s in result.todo) == ["planks"] * 3
    assert sorted(s.material.name for s in result.reused) == ["brick"] * 3


# --- the manifest survives a partial build ----------------------------------

def test_a_partial_build_still_catalogues_every_prefab(tmp_path):
    plan = _kit(tmp_path, materials=("planks", "brick"), widths=(1, 2, 4))
    cache = _cache_with(tmp_path, plan)
    (tmp_path / "textures" / "planks" / "planks_disp_4k.jpg").write_bytes(b"new height")
    result = split(plan.specs, cache, plan.formats, plan.pack_textures, THUMBS, BUILDER)

    fresh = {"prefabs": [_built(tmp_path, s) for s in result.todo]}
    report = merged_report(fresh, cache, result.reused)
    manifest = compose(plan, report)

    assert manifest["counts"]["prefabs"] == 6
    assert all(p["files"].get("blend") for p in manifest["prefabs"])
    assert {m["id"] for m in manifest["materials"]} == {"planks", "brick"}


def test_merging_prefers_what_was_just_built(tmp_path):
    plan = _kit(tmp_path)
    cache = _cache_with(tmp_path, plan)
    spec = plan.specs[0]
    fresh = {"prefabs": [dict(_built(tmp_path, spec), vertices=4182)]}
    report = merged_report(fresh, cache, plan.specs)
    assert len(report["prefabs"]) == 1 and report["prefabs"][0]["vertices"] == 4182


def test_merging_skips_a_prefab_the_cache_never_saw(tmp_path):
    plan = _kit(tmp_path)
    cache = Cache.empty(str(tmp_path / "build"))
    report = merged_report({"prefabs": []}, cache, plan.specs)
    assert report["prefabs"] == []


# --- persistence ------------------------------------------------------------

def test_the_cache_round_trips(tmp_path):
    plan = _kit(tmp_path)
    _cache_with(tmp_path, plan).save()
    reloaded = Cache.load(str(tmp_path / "build"))
    spec = plan.specs[0]
    key = reloaded.key(spec.to_dict(), plan.formats, plan.pack_textures, BUILDER)
    assert reloaded.stale(spec, key, THUMBS) is None


def test_a_cache_from_another_version_is_discarded(tmp_path):
    plan = _kit(tmp_path)
    cache = _cache_with(tmp_path, plan)
    cache.save()
    path = tmp_path / "build" / cache_mod.CACHE_NAME
    path.write_text(path.read_text().replace(f'"version": {cache_mod.CACHE_VERSION}',
                                             '"version": 999'))
    assert Cache.load(str(tmp_path / "build")).prefabs == {}


def test_a_corrupt_cache_means_a_full_build_not_a_crash(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / cache_mod.CACHE_NAME).write_text("{not json")
    assert Cache.load(str(tmp_path / "build")).prefabs == {}


def test_a_missing_cache_means_a_full_build(tmp_path):
    assert Cache.load(str(tmp_path / "nowhere")).prefabs == {}


def test_saving_forgets_textures_that_are_gone(tmp_path):
    path = tmp_path / "tex.jpg"
    path.write_bytes(b"bytes")
    cache = Cache.empty(str(tmp_path / "build"))
    cache.digest(str(path))
    os.unlink(path)
    cache.save()
    assert Cache.load(str(tmp_path / "build")).digests == {}


def test_prefabs_dropped_from_the_config_are_reported(tmp_path):
    plan = _kit(tmp_path, widths=(1, 2, 4))
    cache = _cache_with(tmp_path, plan)
    live = [s.id for s in plan.specs[:2]]
    assert cache.orphans(live) == [plan.specs[2].id]
    cache.forget(cache.orphans(live))
    assert cache.orphans(live) == []
