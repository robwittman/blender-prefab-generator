"""Locating texture map files on disk.

Downloads from ambientCG / cc0-textures name their files systematically -
``Bricks075A_2K-JPG_Color.jpg``, ``_NormalGL.jpg``, ``_Roughness.jpg`` - and other
sources use their own conventions. Rather than making every material spell out four
paths, the material folder is scanned and files are matched to roles by their trailing
token. Anything the scan gets wrong can be overridden per role in the config.
"""
from __future__ import annotations

import os
import re

TEXTURE_EXTS = (".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr", ".webp")

# Role -> accepted trailing tokens, most preferred first. NormalGL wins over plain
# "normal" so an ambientCG folder containing both conventions picks the right one.
ROLE_TOKENS = {
    "albedo": ("albedo", "color", "colour", "basecolor", "basecolour", "diffuse", "albedotransparency", "col", "diff"),
    "normal": ("normalgl", "normalopengl", "norgl", "normal", "nrm", "nor"),
    "roughness": ("roughness", "rough", "rgh"),
    "metallic": ("metallic", "metalness", "metal", "mtl"),
    "ao": ("ambientocclusion", "ambientocclusionmap", "occlusion", "ao"),
    "height": ("displacement", "disp", "height", "hgt"),
}
# Tokens that mean "normal map, but DirectX convention" - usable, needs its green
# channel inverted before Blender's Normal Map node sees it.
DX_TOKENS = ("normaldx", "normaldirectx", "nordx")
SPLIT = re.compile(r"[-_. ]+")
NO_MATCH = (None, False, 0)


def _tokens(filename: str) -> list:
    stem = os.path.splitext(os.path.basename(filename))[0]
    return [t for t in SPLIT.split(stem.lower()) if t]


def _candidates(toks: list):
    """Token n-grams to test, rightmost first, longer before shorter at a position.

    Conventions differ in where the map type sits: ambientCG puts it last
    (``Bricks075A_2K-JPG_Color``) while Poly Haven buries it in the middle
    (``brick_4_diff_4k``, where the trailing token is the resolution). Scanning from
    the right finds both, and preferring the two-token form first keeps Poly Haven's
    split ``nor_gl`` / ``nor_dx`` from being read as a bare, convention-less "nor".
    """
    for i in range(len(toks) - 1, -1, -1):
        if i > 0:
            yield toks[i - 1] + toks[i]
        yield toks[i]


def _match(filename: str):
    """Return (role, is_directx, preference) - preference orders equally valid names."""
    for token in _candidates(_tokens(filename)):
        if token in DX_TOKENS:
            return "normal", True, DX_TOKENS.index(token)
        for role, accepted in ROLE_TOKENS.items():
            if token in accepted:
                return role, False, accepted.index(token)
    return NO_MATCH


def classify(filename: str):
    """Return (role, is_directx) for a texture filename, or (None, False)."""
    role, is_dx, _ = _match(filename)
    return role, is_dx


def scan(folder: str):
    """Find one file per role under ``folder`` (recursively).

    Returns (maps, flip_green, ambiguous) where ``ambiguous`` lists roles that matched
    more than one file, so the caller can tell the user to disambiguate in config.
    """
    if not os.path.isdir(folder):
        return {}, False, []

    candidates: dict = {}
    for root, _dirs, files in os.walk(folder):
        for fname in files:
            if not fname.lower().endswith(TEXTURE_EXTS):
                continue
            role, is_dx, pref = _match(fname)
            if role:
                candidates.setdefault(role, []).append((os.path.join(root, fname), is_dx, pref))

    maps, flip_green, ambiguous = {}, False, []
    for role, found in candidates.items():
        if len(found) > 1:
            ambiguous.append(role)
        # OpenGL normals beat DirectX; then the earliest-listed token name; then the
        # shortest path, so a top-level file wins over one nested in a subfolder.
        best_path, best_dx, _ = sorted(found, key=lambda i: (i[1], i[2], len(i[0]), i[0]))[0]
        maps[role] = best_path
        if role == "normal" and best_dx:
            flip_green = True
    return maps, flip_green, sorted(ambiguous)
