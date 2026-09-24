#!/usr/bin/env python3
"""
Procedural, rigged, mobile-ready GLB generator for a stylized dragon whelp.

    python build_dragon_whelp.py                # -> dragon_whelp.glb
    python build_dragon_whelp.py -o out.glb --texture-size 1024

Design brief
------------
Small stylized fantasy dragon whelp, full body, standing on four legs in a
wide A-pose (limbs separated, wings spread horizontally), head forward and
level, tail straight back, feet flat on the ground. Stubby rounded body,
oversized head, short blunt horns, small ridged spine plates, wings shorter
than the body. Emerald scales, amber underbelly, bronze claws. Hand-painted
look, symmetrical neutral rest pose, no base.

Output (glTF 2.0 binary, Y-up, +Z forward, metres, ground at y=0)
------------------------------------------------------------------
* one mesh / one primitive / one material  -> a single draw call
* ~11k triangles / ~7k vertices, 16-bit indices
* <= 4 bone influences per vertex (JOINTS_0 / WEIGHTS_0)
* 35-joint quadruped + wing skeleton with .L/.R naming
* baseColor = embedded hand-painted atlas (sRGB PNG) x COLOR_0 tint
* baked clips: Idle, Walk, Flap, Roar

Only depends on numpy and Pillow.
"""

import argparse
import io
import json
import math
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

RNG = np.random.default_rng(7)

# ---------------------------------------------------------------------------
# Palette (authored in sRGB, converted to linear for COLOR_0)
# ---------------------------------------------------------------------------


def hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


EMERALD_DARK = hex_rgb("#17603A")
EMERALD = hex_rgb("#2A9453")
EMERALD_LIGHT = hex_rgb("#5CC46E")
AMBER = hex_rgb("#FFB840")
AMBER_LIGHT = hex_rgb("#FFD27A")
BRONZE_DARK = hex_rgb("#6E4520")
BRONZE = hex_rgb("#B07A34")
BRONZE_LIGHT = hex_rgb("#E2B266")
HORN = hex_rgb("#C9A06A")
HORN_TIP = hex_rgb("#F1DDB0")
PLATE = hex_rgb("#E08A2E")
PLATE_TIP = hex_rgb("#FFC45E")
MEMBRANE = hex_rgb("#3E9E5E")
MEMBRANE_EDGE = hex_rgb("#C9C25A")
NOSTRIL = hex_rgb("#12301E")
WHITE = np.ones(3)

# ---------------------------------------------------------------------------
# Texture atlas layout (glTF UV: origin top-left)
#   scales   : u 0..1     v 0.00..0.50   (tiles horizontally, loft skin)
#   eye      : u 0..0.25  v 0.50..0.75
#   strokes  : u 0..0.25  v 0.75..1.00   (horns, claws, plates)
#   membrane : u 0.25..1  v 0.50..1.00   (wing webbing, planar)
# ---------------------------------------------------------------------------
PAD = 0.012
SCALES_V = (PAD, 0.5 - PAD)
EYE_RECT = (PAD, 0.5 + PAD, 0.25 - PAD, 0.75 - PAD)
STROKE_RECT = (PAD, 0.75 + PAD, 0.25 - PAD, 1.0 - PAD)
MEMBRANE_RECT = (0.25 + PAD, 0.5 + PAD, 1.0 - PAD, 1.0 - PAD)
SCALE_V_PER_METRE = 0.55  # scale-rows density along lofts

# ---------------------------------------------------------------------------
# Skeleton (rest pose == bind pose; joints carry translation only)
# name, parent, head (world), tail (world, used for skin-weight segments)
# ---------------------------------------------------------------------------


def mirror(p):
    return (-p[0], p[1], p[2])


BONES = []


def bone(name, parent, head, tail):
    BONES.append(dict(name=name, parent=parent,
                      head=np.array(head, float), tail=np.array(tail, float)))


def build_skeleton():
    bone("root", None, (0, 0, 0), (0, 0, 0.1))
    bone("hips", "root", (0, 0.32, -0.10), (0, 0.335, 0.03))
    bone("spine", "hips", (0, 0.335, 0.03), (0, 0.36, 0.14))
    bone("chest", "spine", (0, 0.36, 0.14), (0, 0.40, 0.22))
    bone("neck", "chest", (0, 0.40, 0.22), (0, 0.46, 0.28))
    bone("neck2", "neck", (0, 0.46, 0.28), (0, 0.52, 0.32))
    bone("head", "neck2", (0, 0.52, 0.32), (0, 0.555, 0.52))
    bone("jaw", "head", (0, 0.50, 0.38), (0, 0.475, 0.56))
    tail = [(0, 0.305, -0.24), (0, 0.285, -0.38), (0, 0.268, -0.51),
            (0, 0.253, -0.63), (0, 0.242, -0.74), (0, 0.235, -0.86)]
    parent = "hips"
    for i in range(5):
        bone(f"tail{i + 1}", parent, tail[i], tail[i + 1])
        parent = f"tail{i + 1}"
    for side, s in (("L", 1), ("R", -1)):
        def m(p, s=s):
            return (p[0] * s, p[1], p[2])
        # front legs
        bone(f"upperarm.{side}", "chest", m((0.10, 0.35, 0.15)), m((0.20, 0.22, 0.125)))
        bone(f"forearm.{side}", f"upperarm.{side}", m((0.20, 0.22, 0.125)), m((0.255, 0.075, 0.175)))
        bone(f"hand.{side}", f"forearm.{side}", m((0.255, 0.075, 0.175)), m((0.27, 0.03, 0.25)))
        # hind legs
        bone(f"thigh.{side}", "hips", m((0.10, 0.31, -0.12)), m((0.20, 0.215, -0.07)))
        bone(f"shin.{side}", f"thigh.{side}", m((0.20, 0.215, -0.07)), m((0.245, 0.085, -0.15)))
        bone(f"foot.{side}", f"shin.{side}", m((0.245, 0.085, -0.15)), m((0.26, 0.03, -0.07)))
        # wings
        bone(f"wing1.{side}", "chest", m((0.07, 0.47, 0.10)), m((0.24, 0.515, 0.085)))
        bone(f"wing2.{side}", f"wing1.{side}", m((0.24, 0.515, 0.085)), m((0.40, 0.535, 0.03)))
        bone(f"finger1.{side}", f"wing2.{side}", m((0.40, 0.535, 0.03)), m((0.54, 0.545, -0.05)))
        bone(f"finger2.{side}", f"wing2.{side}", m((0.40, 0.535, 0.03)), m((0.49, 0.535, -0.18)))
        bone(f"finger3.{side}", f"wing2.{side}", m((0.40, 0.535, 0.03)), m((0.33, 0.52, -0.22)))


build_skeleton()
BONE_INDEX = {b["name"]: i for i, b in enumerate(BONES)}


def B(name):
    return BONES[BONE_INDEX[name]]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def normalize(v, axis=-1):
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return v / np.maximum(n, 1e-12)


def catmull_rom(points, samples):
    """Uniform Catmull-Rom through `points` (K,D) -> ((K-1)*samples+1, D)."""
    p = np.asarray(points, float)
    ext = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = []
    for i in range(len(p) - 1):
        p0, p1, p2, p3 = ext[i:i + 4]
        for j in range(samples):
            t = j / samples
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t +
                              (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                              (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(p[-1])
    return np.array(out)


class Part:
    """A chunk of geometry with per-vertex attributes, merged at the end."""

    def __init__(self, pos, tri, uv, col, name):
        self.pos = np.asarray(pos, float)
        self.tri = np.asarray(tri, np.int64)
        self.uv = np.asarray(uv, float)
        self.col = np.asarray(col, float)
        self.name = name
        self.joints = None
        self.weights = None


def loft(path, rx, ry_top, ry_bot=None, segs=16, samples=4, up_hint=(0, 1, 0),
         cap_start=True, cap_end=True, tip_start=0.0, tip_end=0.0):
    """Sweep an (asymmetric) ellipse along a smooth path.

    Returns (pos, tri, ring_t, theta, arclen, (centers, frames)) where ring_t is
    the normalised path parameter of every vertex and theta its angle around
    the path (pi/2 = 'up' side, -pi/2 = 'down' side).
    """
    if ry_bot is None:
        ry_bot = ry_top
    ctrl = np.column_stack([path, rx, ry_top, ry_bot])
    smooth = catmull_rom(ctrl, samples)
    C, RX, RT, RB = smooth[:, :3], smooth[:, 3], smooth[:, 4], smooth[:, 5]
    n = len(C)
    T = np.gradient(C, axis=0)
    T = normalize(T)
    # parallel-transport frames seeded from the up hint
    up = np.array(up_hint, float)
    side0 = np.cross(up, T[0])
    if np.linalg.norm(side0) < 1e-6:
        side0 = np.cross((1, 0, 0), T[0])
    S = [normalize(side0)]
    for i in range(1, n):
        s = S[-1] - np.dot(S[-1], T[i]) * T[i]
        S.append(normalize(s))
    S = np.array(S)
    U = normalize(np.cross(T, S))

    seglen = np.linalg.norm(np.diff(C, axis=0), axis=1)
    arclen = np.concatenate([[0], np.cumsum(seglen)])

    th = np.linspace(0, 2 * np.pi, segs + 1)  # duplicated seam for UVs
    cos, sin = np.cos(th), np.sin(th)
    ry = np.where(sin[None, :] >= 0, RT[:, None], RB[:, None])
    pos = (C[:, None, :] + S[:, None, :] * (RX[:, None] * cos[None, :])[..., None]
           + U[:, None, :] * (ry * sin[None, :])[..., None])
    pos = pos.reshape(-1, 3)
    ring_t = np.repeat(np.linspace(0, 1, n), segs + 1)
    theta = np.tile(th, n)
    alen = np.repeat(arclen, segs + 1)

    tris = []
    w = segs + 1
    for i in range(n - 1):
        for j in range(segs):
            a, b = i * w + j, i * w + j + 1
            c, d = a + w, b + w
            tris += [(a, b, c), (b, d, c)]
    extra_pos, extra_t, extra_th, extra_len = [], [], [], []
    if cap_start:
        idx = len(pos) + len(extra_pos)
        extra_pos.append(C[0] - T[0] * tip_start)
        extra_t.append(0.0), extra_th.append(0.0), extra_len.append(-tip_start)
        for j in range(segs):
            tris.append((idx, j + 1, j))
    if cap_end:
        idx = len(pos) + len(extra_pos)
        extra_pos.append(C[-1] + T[-1] * tip_end)
        extra_t.append(1.0), extra_th.append(0.0), extra_len.append(arclen[-1] + tip_end)
        base = (n - 1) * w
        for j in range(segs):
            tris.append((idx, base + j, base + j + 1))
    if extra_pos:
        pos = np.vstack([pos, extra_pos])
        ring_t = np.concatenate([ring_t, extra_t])
        theta = np.concatenate([theta, extra_th])
        alen = np.concatenate([alen, extra_len])
    return pos, np.array(tris), ring_t, theta, alen


def ellipsoid(center, radii, rot=np.eye(3), lat=10, lon=16):
    """UV sphere. Returns pos, tri, theta(lon angle), phi(lat 0..1 bottom->top)."""
    center = np.asarray(center, float)
    ph = np.linspace(-np.pi / 2, np.pi / 2, lat + 1)
    th = np.linspace(0, 2 * np.pi, lon + 1)
    P, Th = np.meshgrid(ph, th, indexing="ij")
    local = np.stack([np.cos(P) * np.cos(Th), np.sin(P), np.cos(P) * np.sin(Th)], -1)
    local = local.reshape(-1, 3) * np.asarray(radii, float)
    pos = local @ np.asarray(rot).T + center
    tris = []
    w = lon + 1
    for i in range(lat):
        for j in range(lon):
            a, b = i * w + j, i * w + j + 1
            c, d = a + w, b + w
            tris += [(a, c, b), (b, c, d)]
    phi01 = (P.reshape(-1) + np.pi / 2) / np.pi
    return pos, np.array(tris), Th.reshape(-1), phi01


def rot_from_forward(fwd, up=(0, 1, 0)):
    """Rotation whose local +Z points along `fwd` and +Y roughly along `up`."""
    z = normalize(np.asarray(fwd, float))
    x = normalize(np.cross(up, z))
    y = np.cross(z, x)
    return np.column_stack([x, y, z])


def rect_uv(rect, u, v):
    u0, v0, u1, v1 = rect
    return np.column_stack([u0 + (u1 - u0) * np.clip(u, 0, 1),
                            v0 + (v1 - v0) * np.clip(v, 0, 1)])


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    t = np.asarray(t, float)[..., None]
    return a * (1 - t) + b * t


# ---------------------------------------------------------------------------
# Hand-painted vertex tint helpers
# ---------------------------------------------------------------------------


def scale_skin_color(pos, theta, belly_strength=1.0, belly_lo=-0.05, belly_hi=-0.45):
    """Emerald back fading to lighter flanks, amber underbelly on the down side."""
    s = np.sin(theta)
    top = smoothstep(-0.2, 1.0, s)
    col = lerp(EMERALD, EMERALD_DARK, top * 0.85)
    col = lerp(col, EMERALD_LIGHT, smoothstep(0.35, -0.1, s) * (1 - smoothstep(-0.1, -0.35, s)) * 0.55)
    belly = smoothstep(belly_lo, belly_hi, s) * belly_strength
    bcol = lerp(AMBER, AMBER_LIGHT, smoothstep(-0.7, -1.0, s))
    return lerp(col, bcol, belly)


def skin_uv(theta, arclen):
    u = theta / (2 * np.pi)
    v = SCALES_V[0] + np.clip(arclen * SCALE_V_PER_METRE, 0, 1) * (SCALES_V[1] - SCALES_V[0])
    return np.column_stack([u, v])


# ---------------------------------------------------------------------------
# Model parts
# ---------------------------------------------------------------------------
PARTS = []


def add(part, bones_, rigid=False):
    part.bones = bones_
    part.rigid = rigid
    PARTS.append(part)
    return part


def build_body():
    # tail tip -> hips -> belly -> chest -> neck (ends inside the head)
    spine = [
        # z,      y,     rx,    ry_top, ry_bot
        (-0.88, 0.233, 0.010, 0.010, 0.010),
        (-0.80, 0.240, 0.024, 0.024, 0.022),
        (-0.68, 0.250, 0.038, 0.038, 0.034),
        (-0.54, 0.265, 0.054, 0.054, 0.050),
        (-0.40, 0.283, 0.074, 0.074, 0.070),
        (-0.27, 0.300, 0.105, 0.104, 0.102),
        (-0.15, 0.318, 0.145, 0.142, 0.150),
        (-0.03, 0.330, 0.168, 0.160, 0.178),
        (0.07, 0.342, 0.170, 0.165, 0.175),
        (0.16, 0.360, 0.150, 0.160, 0.155),
        (0.23, 0.400, 0.105, 0.110, 0.105),
        (0.29, 0.460, 0.086, 0.088, 0.086),
        (0.33, 0.510, 0.080, 0.080, 0.080),
    ]
    sp = np.array(spine)
    path = np.column_stack([np.zeros(len(sp)), sp[:, 1], sp[:, 0]])
    pos, tri, t, th, al = loft(path, sp[:, 2], sp[:, 3], sp[:, 4], segs=18, samples=3,
                               tip_start=0.012)
    col = scale_skin_color(pos, th)
    uv = skin_uv(th, al)
    add(Part(pos, tri, uv, col, "body"),
        ["hips", "spine", "chest", "neck", "neck2", "head",
         "tail1", "tail2", "tail3", "tail4", "tail5"])

    # little spade at the tail tip (flat, horizontal)
    tip = np.array([0, 0.234, -0.86])
    pos, tri, _, phi = ellipsoid(tip + (0, 0, -0.03), (0.055, 0.012, 0.06), lat=6, lon=12)
    # make it a diamond / spade: pinch the rear
    z = pos[:, 2] - (tip[2] - 0.03)
    pos[:, 0] *= np.clip(1.0 + z / 0.06 * 0.35, 0.2, 1.4)
    col = lerp(PLATE, PLATE_TIP, smoothstep(0.03, 0.09, -z))
    uv = rect_uv(STROKE_RECT, 0.5 + pos[:, 0] * 4, -z / 0.12 + 0.5)
    add(Part(pos, tri, uv, col, "tail_spade"), ["tail5"], rigid=True)


def build_head():
    # skull + snout loft, back of skull -> nose
    prof = [
        # z,     y,     rx,    ry_top, ry_bot
        (0.215, 0.555, 0.040, 0.040, 0.040),
        (0.245, 0.560, 0.105, 0.105, 0.090),
        (0.290, 0.565, 0.140, 0.130, 0.110),
        (0.345, 0.565, 0.148, 0.130, 0.105),
        (0.400, 0.558, 0.132, 0.110, 0.080),
        (0.450, 0.548, 0.105, 0.080, 0.060),
        (0.500, 0.540, 0.090, 0.064, 0.048),
        (0.545, 0.534, 0.080, 0.056, 0.042),
        (0.575, 0.530, 0.062, 0.044, 0.034),
        (0.592, 0.528, 0.030, 0.022, 0.018),
    ]
    p = np.array(prof)
    path = np.column_stack([np.zeros(len(p)), p[:, 1], p[:, 0]])
    pos, tri, t, th, al = loft(path, p[:, 2], p[:, 3], p[:, 4], segs=20, samples=3,
                               tip_start=0.01, tip_end=0.006)
    col = scale_skin_color(pos, th, belly_strength=0.9, belly_lo=-0.45, belly_hi=-0.8)
    # lighter muzzle
    col = lerp(col, EMERALD_LIGHT, smoothstep(0.47, 0.58, pos[:, 2]) * 0.35 * (np.sin(th) > -0.3))
    uv = skin_uv(th, al + 0.2)
    add(Part(pos, tri, uv, col, "head"), ["head", "neck2"])

    # lower jaw (overlaps under the snout -> readable mouth crease)
    jp = [
        (0.33, 0.500, 0.105, 0.035, 0.050),
        (0.40, 0.492, 0.100, 0.034, 0.046),
        (0.46, 0.486, 0.083, 0.030, 0.040),
        (0.52, 0.482, 0.068, 0.026, 0.032),
        (0.565, 0.482, 0.050, 0.020, 0.024),
        (0.580, 0.483, 0.022, 0.012, 0.012),
    ]
    p = np.array(jp)
    path = np.column_stack([np.zeros(len(p)), p[:, 1], p[:, 0]])
    pos, tri, t, th, al = loft(path, p[:, 2], p[:, 3], p[:, 4], segs=16, samples=3,
                               tip_end=0.004)
    col = scale_skin_color(pos, th, belly_strength=1.0, belly_lo=0.1, belly_hi=-0.4)
    uv = skin_uv(th, al + 0.5)
    add(Part(pos, tri, uv, col, "jaw"), ["jaw"], rigid=True)

    for s in (1, -1):
        # brow ridge
        c = np.array([0.075 * s, 0.645, 0.395])
        rot = rot_from_forward((0.25 * s, 0.1, 1.0))
        pos, tri, th, phi = ellipsoid(c, (0.045, 0.022, 0.060), rot, lat=8, lon=12)
        col = lerp(EMERALD, EMERALD_DARK, phi * 0.9)
        uv = skin_uv(th, phi * 0.2 + 0.9)
        add(Part(pos, tri, uv, col, "brow"), ["head"], rigid=True)

        # big eye, painted via atlas
        c = np.array([0.098 * s, 0.598, 0.418])
        look = normalize(np.array([0.72 * s, 0.12, 0.68]))
        r = 0.042
        rot = rot_from_forward(look)
        pos, tri, th, phi = ellipsoid(c, (r, r, r * 0.8), rot, lat=10, lon=16)
        local = (pos - c) @ rot
        uv = rect_uv(EYE_RECT, 0.5 + 0.5 * local[:, 0] / r * s, 0.5 - 0.5 * local[:, 1] / r)
        col = np.tile(WHITE, (len(pos), 1))
        add(Part(pos, tri, uv, col, "eye"), ["head"], rigid=True)

        # nostrils
        c = np.array([0.03 * s, 0.566, 0.585])
        pos, tri, th, phi = ellipsoid(c, (0.011, 0.007, 0.008), lat=5, lon=8)
        uv = rect_uv(STROKE_RECT, np.full(len(pos), 0.5), np.full(len(pos), 0.1))
        col = np.tile(NOSTRIL, (len(pos), 1))
        add(Part(pos, tri, uv, col, "nostril"), ["head"], rigid=True)

        # short blunt horns, sweeping back and slightly out
        base = np.array([0.062 * s, 0.655, 0.300])
        path = np.array([base - np.array([0.01 * s, 0.03, -0.01]),
                         base,
                         base + np.array([0.022 * s, 0.035, -0.045]),
                         base + np.array([0.040 * s, 0.050, -0.095])])
        pos, tri, t, th, al = loft(path, [0.034, 0.030, 0.021, 0.012], [0.034, 0.030, 0.021, 0.012],
                                   segs=10, samples=3, up_hint=(0, 0, -1), cap_start=False,
                                   tip_end=0.010)
        col = lerp(HORN, HORN_TIP, smoothstep(0.3, 1.0, t))
        uv = rect_uv(STROKE_RECT, th / (2 * np.pi), t)
        add(Part(pos, tri, uv, col, "horn"), ["head"], rigid=True)

        # tiny second horn nub
        base = np.array([0.105 * s, 0.63, 0.305])
        path = np.array([base - np.array([0.012 * s, 0.01, -0.01]), base,
                         base + np.array([0.03 * s, 0.012, -0.035])])
        pos, tri, t, th, al = loft(path, [0.018, 0.016, 0.007], [0.018, 0.016, 0.007],
                                   segs=8, samples=2, up_hint=(0, 0, -1), cap_start=False,
                                   tip_end=0.006)
        col = lerp(HORN, HORN_TIP, t)
        uv = rect_uv(STROKE_RECT, th / (2 * np.pi), t)
        add(Part(pos, tri, uv, col, "horn_nub"), ["head"], rigid=True)


def build_spine_plates():
    # (z, approx surface y, height, half length, bones) from the skull back along the tail
    plates = [
        (0.265, 0.648, 0.032, 0.020, ["head"]),
        (0.225, 0.535, 0.030, 0.020, ["neck2"]),
        (0.175, 0.500, 0.036, 0.024, ["neck", "chest"]),
        (0.105, 0.487, 0.042, 0.027, ["chest"]),
        (0.020, 0.470, 0.045, 0.028, ["spine"]),
        (-0.070, 0.462, 0.044, 0.027, ["spine", "hips"]),
        (-0.160, 0.440, 0.040, 0.025, ["hips"]),
        (-0.255, 0.388, 0.034, 0.022, ["hips", "tail1"]),
        (-0.350, 0.345, 0.028, 0.019, ["tail1", "tail2"]),
        (-0.450, 0.318, 0.023, 0.016, ["tail2", "tail3"]),
        (-0.550, 0.295, 0.019, 0.013, ["tail3", "tail4"]),
        (-0.650, 0.278, 0.015, 0.011, ["tail4", "tail5"]),
        (-0.745, 0.262, 0.012, 0.009, ["tail5"]),
    ]
    # snap each plate onto the dorsal midline of the already-built body / head
    surf = np.vstack([pt.pos for pt in PARTS if pt.name in ("body", "head")])
    surf = surf[np.abs(surf[:, 0]) < 0.03]
    for z, _, h, hl, bones_ in plates:
        near = surf[np.abs(surf[:, 2] - z) < 0.03]
        y = near[:, 1].max()
        base = np.array([0, y - 0.018, z])
        path = np.array([base, base + (0, 0.018 + h * 0.5, -h * 0.25),
                         base + (0, 0.018 + h, -h * 0.55)])
        h, hl = h * 1.45, hl * 1.3
        th_ = max(0.008, hl * 0.33)
        pos, tri, t, th, al = loft(path, [th_, th_ * 0.8, th_ * 0.3], [hl, hl * 0.7, hl * 0.12],
                                   segs=8, samples=2, up_hint=(0, 0, 1), cap_start=False,
                                   tip_end=0.004)
        # ridged: darken the vertical centre groove
        ridge = np.abs(np.cos(th))
        col = lerp(PLATE, PLATE_TIP, smoothstep(0.35, 1.0, t))
        col = col * (0.82 + 0.18 * ridge[:, None])
        uv = rect_uv(STROKE_RECT, th / (2 * np.pi), t)
        add(Part(pos, tri, uv, col, "plate"), bones_, rigid=len(bones_) == 1)


def claw(tip_base, direction, length, radius, bones_):
    d = normalize(np.asarray(direction, float))
    down = np.array([0, -1, 0])
    path = np.array([tip_base - d * radius, tip_base + d * length * 0.5 + down * length * 0.08,
                     tip_base + d * length + down * length * 0.35])
    pos, tri, t, th, al = loft(path, [radius, radius * 0.75, radius * 0.18],
                               [radius, radius * 0.75, radius * 0.18], segs=6, samples=2,
                               cap_start=False, tip_end=0.003)
    col = lerp(BRONZE_DARK, lerp(BRONZE, BRONZE_LIGHT, t), smoothstep(0.0, 0.25, t))
    uv = rect_uv(STROKE_RECT, th / (2 * np.pi), t)
    add(Part(pos, tri, uv, col, "claw"), bones_, rigid=True)


def build_legs():
    for s, side in ((1, "L"), (-1, "R")):
        def m(p, s=s):
            return np.array([p[0] * s, p[1], p[2]])

        for kind in ("front", "hind"):
            if kind == "front":
                pts = [m((0.06, 0.39, 0.13)), B(f"upperarm.{side}")["head"], B(f"forearm.{side}")["head"],
                       B(f"hand.{side}")["head"], m((0.262, 0.05, 0.18))]
                rad = [0.08, 0.08, 0.06, 0.048, 0.046]
                chain = [f"upperarm.{side}", f"forearm.{side}", f"hand.{side}", "chest"]
                paw_c = m((0.268, 0.034, 0.20))
                paw_r = (0.058, 0.036, 0.068)
                end_bone = f"hand.{side}"
            else:
                pts = [m((0.05, 0.34, -0.12)), B(f"thigh.{side}")["head"], B(f"shin.{side}")["head"],
                       B(f"foot.{side}")["head"], m((0.252, 0.05, -0.13))]
                rad = [0.11, 0.108, 0.07, 0.05, 0.048]
                chain = [f"thigh.{side}", f"shin.{side}", f"foot.{side}", "hips"]
                paw_c = m((0.255, 0.034, -0.11))
                paw_r = (0.060, 0.036, 0.072)
                end_bone = f"foot.{side}"

            pos, tri, t, th, al = loft(np.array(pts), rad, rad, segs=12, samples=3,
                                       up_hint=(0, 0, 1), cap_start=True, cap_end=True)
            # theta measured around a leg: 'down' side faces backwards/inwards,
            # keep it green with lighter inner side
            n_out = np.sin(th)
            col = lerp(EMERALD, EMERALD_DARK, smoothstep(-0.2, 1.0, np.cos(th) * s) * 0.6)
            col = lerp(col, EMERALD_LIGHT, smoothstep(0.2, 0.9, n_out) * 0.35)
            col = lerp(col, AMBER, smoothstep(0.25, 0.0, t) * smoothstep(-0.2, -0.8, np.cos(th) * s) * 0.6)
            uv = skin_uv(th, al + (0.3 if kind == "front" else 0.6))
            add(Part(pos, tri, uv, col, f"{kind}_leg"), chain)

            # flat-bottomed paw
            pos, tri, th, phi = ellipsoid(paw_c, paw_r, rot_from_forward((0.12 * s, 0, 1)), lat=8, lon=14)
            pos[:, 1] = np.maximum(pos[:, 1], 0.0)
            col = lerp(EMERALD_DARK, EMERALD, smoothstep(0.2, 0.8, phi))
            col = lerp(col, BRONZE_DARK, smoothstep(0.35, 0.15, phi) * 0.5)
            uv = skin_uv(th, phi * 0.15 + 1.2)
            add(Part(pos, tri, uv, col, "paw"), [end_bone], rigid=True)

            # three chubby toes + bronze claws
            fwd = normalize(np.array([0.12 * s, 0, 1.0]))
            right = normalize(np.cross((0, 1, 0), fwd))
            for k, off in enumerate((-1, 0, 1)):
                tdir = normalize(fwd + right * off * 0.35)
                tc = paw_c + tdir * (paw_r[2] * 0.85) + np.array([0, -0.004, 0])
                pos, tri, th, phi = ellipsoid(tc, (0.022, 0.024, 0.03), rot_from_forward(tdir), lat=5, lon=8)
                pos[:, 1] = np.maximum(pos[:, 1], 0.0)
                col = lerp(EMERALD_DARK, EMERALD, phi)
                uv = skin_uv(th, phi * 0.1 + 1.3)
                add(Part(pos, tri, uv, col, "toe"), [end_bone], rigid=True)
                claw(tc + tdir * 0.022 + np.array([0, 0.004, 0]), tdir, 0.034, 0.011, [end_bone])


def build_wings():
    for s, side in ((1, "L"), (-1, "R")):
        w1, w2 = B(f"wing1.{side}"), B(f"wing2.{side}")
        f1, f2, f3 = B(f"finger1.{side}"), B(f"finger2.{side}"), B(f"finger3.{side}")
        wrist = w2["tail"]
        root_rear = np.array([0.075 * s, 0.445, -0.13])

        # arm (leading edge) bones
        arm = np.array([w1["head"] + np.array([-0.03 * s, -0.02, 0.0]), w1["head"], w1["tail"], wrist])
        pos, tri, t, th, al = loft(arm, [0.036, 0.034, 0.026, 0.02], [0.036, 0.034, 0.026, 0.02],
                                   segs=12, samples=3, up_hint=(0, 1, 0), tip_end=0.012)
        col = scale_skin_color(pos, th, belly_strength=0.5)
        uv = skin_uv(th, al + 0.8)
        add(Part(pos, tri, uv, col, "wing_arm"), [f"wing1.{side}", f"wing2.{side}", "chest"])

        # wrist thumb claw
        claw(wrist + np.array([0.004 * s, 0.018, 0.012]), (0.35 * s, 0.35, 1.0), 0.03, 0.011,
             [f"wing2.{side}"])

        # finger struts
        for f in (f1, f2, f3):
            path = np.array([f["head"], lerp(f["head"], f["tail"], 0.5) + np.array([0, 0.006, 0]), f["tail"]])
            pos, tri, t, th, al = loft(path, [0.016, 0.012, 0.006], [0.016, 0.012, 0.006], segs=6,
                                       samples=3, tip_end=0.006)
            col = lerp(EMERALD_DARK, EMERALD, t)
            uv = skin_uv(th, al + 1.0)
            add(Part(pos, tri, uv, col, "finger"), [f["name"], f"wing2.{side}"])

        # membrane panels, fanned from the wrist
        inner_edge = [wrist, w1["tail"], w1["head"] + np.array([0.0, -0.02, -0.03]), root_rear]
        edges = [
            [wrist, f1["tail"]],
            [wrist, f2["tail"]],
            [wrist, f3["tail"]],
            inner_edge,
        ]
        scallop = [0.16, 0.20, 0.26]
        nu, nv = 9, 7
        for pi in range(3):
            A = resample_polyline(np.array(edges[pi]), nu)
            Bp = resample_polyline(np.array(edges[pi + 1]), nu)
            P, uu, vv = [], [], []
            for i in range(nu):
                for j in range(nv):
                    u = i / (nu - 1)
                    v = j / (nv - 1)
                    # scallop the trailing edge between struts
                    ue = u * (1 - scallop[pi] * math.sin(math.pi * v) * u ** 3)
                    a = sample_polyline(A, ue)
                    b = sample_polyline(Bp, ue)
                    p = a * (1 - v) + b * v
                    # gentle billow downward in the middle of each panel
                    p = p + np.array([0, -0.012 * math.sin(math.pi * v) * math.sin(math.pi * ue * 0.9), 0])
                    P.append(p)
                    uu.append(ue)
                    vv.append(v)
            P, uu, vv = np.array(P), np.array(uu), np.array(vv)
            tri = []
            for i in range(nu - 1):
                for j in range(nv - 1):
                    a, b = i * nv + j, i * nv + j + 1
                    c, d = a + nv, b + nv
                    tri += [(a, c, b), (b, c, d)]
            tri = np.array(tri)
            # make sure the top face points up
            n0 = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
            if n0[:, 1].sum() < 0:
                tri = tri[:, [0, 2, 1]]
            col = lerp(MEMBRANE, MEMBRANE_EDGE, smoothstep(0.45, 1.0, uu) * 0.75)
            col = col * (0.9 + 0.1 * np.sin(math.pi * vv))[:, None]
            span = 0.62
            uv = rect_uv(MEMBRANE_RECT, 0.5 + P[:, 0] * s / span * 0.95 - 0.35, 0.5 - P[:, 2] / span * 1.1)
            thick = 0.0025
            top = P + np.array([0, thick, 0])
            bot = P - np.array([0, thick, 0])
            bones_ = [f"wing1.{side}", f"wing2.{side}", f"finger1.{side}", f"finger2.{side}",
                      f"finger3.{side}", "chest", "spine"]
            add(Part(top, tri, uv, col, "membrane_top"), bones_)
            add(Part(bot, tri[:, [0, 2, 1]], uv, col * 0.82, "membrane_bottom"), bones_)


def resample_polyline(pts, n):
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)]) / seg.sum()
    return np.array([np.array([np.interp(t, cum, pts[:, k]) for k in range(3)])
                     for t in np.linspace(0, 1, n)])


def sample_polyline(pts, t):
    f = t * (len(pts) - 1)
    i = min(int(f), len(pts) - 2)
    return lerp(pts[i], pts[i + 1], f - i)


# ---------------------------------------------------------------------------
# Skin weights
# ---------------------------------------------------------------------------


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def compute_weights(part):
    n = len(part.pos)
    if part.rigid or len(part.bones) == 1:
        j = np.zeros((n, 4), np.int64)
        w = np.zeros((n, 4))
        j[:, 0] = BONE_INDEX[part.bones[0]]
        w[:, 0] = 1.0
        return j, w
    ids = np.array([BONE_INDEX[b] for b in part.bones])
    D = np.stack([seg_dist(part.pos, BONES[i]["head"], BONES[i]["tail"]) for i in ids], 1)
    W = 1.0 / np.maximum(D, 0.004) ** 4
    order = np.argsort(-W, axis=1)[:, :4]
    k = min(4, len(ids))
    top = np.take_along_axis(W, order, 1)[:, :k]
    jid = ids[order[:, :k]]
    # prune tiny influences and quantise-friendly normalise
    top = np.where(top / top[:, :1] < 0.03, 0, top)
    top = top / top.sum(1, keepdims=True)
    j = np.zeros((n, 4), np.int64)
    w = np.zeros((n, 4))
    j[:, :k] = jid
    w[:, :k] = top
    j[w == 0] = 0
    return j, w


# ---------------------------------------------------------------------------
# Normals (welded per part so UV seams stay smooth)
# ---------------------------------------------------------------------------


def smooth_normals(pos, tri):
    key = np.round(pos / 1e-5).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    fn = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])
    acc = np.zeros((inv.max() + 1, 3))
    for k in range(3):
        np.add.at(acc, inv[tri[:, k]], fn)
    nrm = normalize(acc[inv])
    bad = np.linalg.norm(nrm, axis=1) < 0.5
    nrm[bad] = (0, 1, 0)
    return nrm


# ---------------------------------------------------------------------------
# Painted lighting baked into the vertex tint (keeps it readable unlit, too)
# ---------------------------------------------------------------------------


def paint_light(col, nrm, pos, part):
    if part.name == "eye":
        return col
    ny = nrm[:, 1]
    key = 0.80 + 0.22 * smoothstep(-0.6, 0.9, ny)
    # soft contact darkening close to the ground
    occl = 0.72 + 0.28 * smoothstep(0.0, 0.12, pos[:, 1])
    return np.clip(col * (key * occl)[:, None], 0, 1)


# ---------------------------------------------------------------------------
# Texture atlas painting
# ---------------------------------------------------------------------------


def paint_texture(size):
    W = H = size
    img = np.ones((H, W, 3))
    yy, xx = np.mgrid[0:H, 0:W].astype(float)

    # --- scales (top half, tiles horizontally) --------------------------
    h2 = H // 2
    cols, rows = 16, 22
    cw, ch = W / cols, h2 / rows
    R = ch * 1.55
    sx, sy = xx[:h2], yy[:h2]
    val = np.full(sx.shape, 0.88)
    assigned = np.zeros(sx.shape, bool)
    base_row = np.floor(sy / ch)
    for dk in (1, 0, -1, -2):  # nearer rows first => they overlap previous
        k = base_row + dk
        off = np.where(np.mod(k, 2) == 1, 0.5, 0.0)
        j = np.round(sx / cw - off - 0.5)
        cx = (j + 0.5 + off) * cw
        cy = k * ch
        dx = sx - cx
        dx = dx - W * np.round(dx / W)
        dy = sy - cy
        # upside-down "U" scale shape: body hangs below the centre
        ex_ = dx * (2 * R / cw) * 0.62
        inside = (dy >= -R * 0.2) & (ex_ * ex_ + dy * dy < R * R) & ~assigned
        d = np.sqrt(ex_ * ex_ + dy * dy) / R
        shade = 1.0 - 0.10 * (dy / R)          # lighter at top of scale
        shade = shade - 0.42 * smoothstep(0.62, 1.0, d)   # painted dark rim
        shade = shade + 0.10 * smoothstep(0.45, 0.0, np.hypot(ex_ + R * 0.15, dy - R * 0.1) / R)  # highlight
        # per-scale hue jitter
        rnd = np.sin(j * 12.9898 + k * 78.233) * 43758.5453
        rnd = rnd - np.floor(rnd)
        shade = shade * (0.94 + 0.08 * rnd)
        val = np.where(inside, shade, val)
        assigned |= inside
    val = np.clip(val, 0.5, 1.0)
    # warm the highlights / cool the rims slightly (painterly)
    scales = val[..., None] + (val[..., None] - 0.88) * np.array([0.15, 0.08, -0.12])
    img[:h2] = np.clip(scales, 0, 1)

    # --- eye (u 0..0.25, v 0.5..0.75) -----------------------------------
    q = W // 4
    ey0 = h2
    ex = (xx[ey0:ey0 + q, :q] + 0.5) / q * 2 - 1
    ey = (yy[ey0:ey0 + q, :q] + 0.5 - ey0) / q * 2 - 1
    r = np.hypot(ex, ey)
    eye = np.zeros((q, q, 3))
    iris_in = hex_rgb("#FFE07A")
    iris_out = hex_rgb("#E07A12")
    eye[:] = lerp(iris_in, iris_out, smoothstep(0.1, 0.8, r))
    eye = lerp(eye, hex_rgb("#3A1E08"), smoothstep(0.72, 0.9, r))
    slit = (ex / 0.17) ** 2 + (ey / 0.72) ** 2
    eye = lerp(eye, hex_rgb("#0B0B0B"), smoothstep(1.1, 0.9, slit))
    hl = np.hypot(ex + 0.32, ey + 0.34)
    eye = lerp(eye, WHITE, smoothstep(0.2, 0.12, hl))
    hl2 = np.hypot(ex - 0.28, ey - 0.35)
    eye = lerp(eye, WHITE, smoothstep(0.1, 0.06, hl2) * 0.8)
    img[ey0:ey0 + q, :q] = eye

    # --- strokes (u 0..0.25, v 0.75..1) : banded horn / claw ------------
    sy0 = h2 + q
    t = (yy[sy0:, :q] - sy0) / (H - sy0)
    u = xx[sy0:, :q] / q
    bands = 0.92 + 0.06 * np.sin(t * 38 + np.sin(u * 2 * np.pi) * 1.5)
    streak = 0.96 + 0.05 * np.sin(u * 2 * np.pi * 6 + t * 3)
    s_val = np.clip(bands * streak * (0.9 + 0.12 * t), 0, 1.05)
    img[sy0:, :q] = np.repeat(s_val[..., None], 3, -1)

    # --- membrane (u 0.25..1, v 0.5..1): mottling + veins ----------------
    mw, mh = W - q, H - h2
    noise = RNG.random((mh // 16 + 2, mw // 16 + 2))
    noise = np.array(Image.fromarray((noise * 255).astype(np.uint8)).resize((mw, mh), Image.BICUBIC)) / 255.0
    mem = 0.92 + 0.08 * noise
    mem_img = Image.fromarray((np.clip(mem, 0, 1) * 255).astype(np.uint8), "L").convert("RGB")
    d = ImageDraw.Draw(mem_img)
    # veins radiating from the wrist area (upper-left of the region)
    origin = np.array([mw * 0.62, mh * 0.18])
    for k in range(14):
        ang = math.radians(35 + k * 9 + RNG.normal(0, 3))
        pts = [tuple(origin)]
        p = origin.copy()
        for step in range(10):
            ang += RNG.normal(0, 0.12)
            p = p + np.array([math.cos(ang), math.sin(ang)]) * mh * 0.07
            pts.append(tuple(p))
        d.line(pts, fill=(196, 196, 196), width=max(1, size // 256))
        # tiny branches
        for bi in range(2, 8, 3):
            bp = np.array(pts[bi])
            ba = ang + RNG.choice([-0.8, 0.8])
            d.line([tuple(bp), tuple(bp + np.array([math.cos(ba), math.sin(ba)]) * mh * 0.08)],
                   fill=(206, 206, 206), width=1)
    mem_img = mem_img.filter(ImageFilter.GaussianBlur(radius=size / 512))
    img[h2:, q:] = np.array(mem_img) / 255.0

    # soft brush blur overall, keep it painterly not noisy
    out = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8), "RGB")
    top = out.crop((0, 0, W, h2)).filter(ImageFilter.GaussianBlur(radius=size / 700))
    out.paste(top, (0, 0))
    return out


# ---------------------------------------------------------------------------
# Animations (local rotations; rest rotation of every joint is identity)
# ---------------------------------------------------------------------------


def quat_axis_angle(axis, ang):
    axis = normalize(np.asarray(axis, float))
    s = math.sin(ang / 2)
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s, math.cos(ang / 2)])


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz])


def euler(x=0.0, y=0.0, z=0.0):
    return qmul(qmul(quat_axis_angle((0, 1, 0), y), quat_axis_angle((1, 0, 0), x)),
                quat_axis_angle((0, 0, 1), z))


def build_animations():
    """Returns {clip: {(joint, path): (times, values)}}; loops are seamless."""
    clips = {}
    fps = 30

    def clip(duration, fn):
        n = int(round(duration * fps)) + 1
        times = np.linspace(0, duration, n)
        tracks = {}
        for i, t in enumerate(times):
            ph = 2 * math.pi * t / duration
            for (jn, path), v in fn(ph).items():
                tracks.setdefault((jn, path), []).append(v)
        return {k: (times, np.array(v)) for k, v in tracks.items()}

    def rest_t(name):
        b = B(name)
        p = b["parent"]
        return b["head"] - (B(p)["head"] if p else 0)

    def idle(ph):
        br = math.sin(ph)
        r = {
            ("hips", "translation"): rest_t("hips") + np.array([0, 0.004 * br, 0]),
            ("spine", "rotation"): euler(x=-0.02 * br),
            ("chest", "rotation"): euler(x=0.025 * br),
            ("neck", "rotation"): euler(x=0.03 * math.sin(ph + 0.6)),
            ("head", "rotation"): euler(x=-0.04 * math.sin(ph + 1.0), y=0.05 * math.sin(ph * 1)),
            ("jaw", "rotation"): euler(x=0.02 * max(0, math.sin(ph))),
        }
        for i in range(1, 6):
            r[(f"tail{i}", "rotation")] = euler(y=0.09 * math.sin(ph - i * 0.55), x=0.02 * math.sin(ph))
        for side, s in (("L", 1), ("R", -1)):
            r[(f"wing1.{side}", "rotation")] = euler(z=s * 0.06 * math.sin(ph + 0.4))
            r[(f"wing2.{side}", "rotation")] = euler(z=s * 0.05 * math.sin(ph + 0.9))
            for f in (1, 2, 3):
                r[(f"finger{f}.{side}", "rotation")] = euler(z=s * 0.04 * math.sin(ph + 1.2 + f * 0.2))
        return r

    def walk(ph):
        r = {
            ("hips", "translation"): rest_t("hips") + np.array([0, 0.008 * math.cos(2 * ph), 0]),
            ("hips", "rotation"): euler(y=0.06 * math.sin(ph), z=0.03 * math.sin(ph)),
            ("chest", "rotation"): euler(y=-0.08 * math.sin(ph), z=-0.03 * math.sin(ph)),
            ("neck", "rotation"): euler(y=0.05 * math.sin(ph)),
            ("head", "rotation"): euler(x=0.03 * math.cos(2 * ph), y=0.03 * math.sin(ph)),
        }
        for i in range(1, 6):
            r[(f"tail{i}", "rotation")] = euler(y=0.12 * math.sin(ph - 0.6 - i * 0.5))
        # diagonal gait: front.L with hind.R
        for side, s, off in (("L", 1, 0.0), ("R", -1, math.pi)):
            a = ph + off
            r[(f"upperarm.{side}", "rotation")] = euler(x=-0.45 * math.sin(a))
            r[(f"forearm.{side}", "rotation")] = euler(x=0.5 * max(0, math.cos(a)) ** 1.5)
            r[(f"hand.{side}", "rotation")] = euler(x=0.45 * math.sin(a) - 0.3 * max(0, math.cos(a)))
            b = a + math.pi
            r[(f"thigh.{side}", "rotation")] = euler(x=-0.4 * math.sin(b))
            r[(f"shin.{side}", "rotation")] = euler(x=-0.45 * max(0, math.cos(b)) ** 1.5)
            r[(f"foot.{side}", "rotation")] = euler(x=0.4 * math.sin(b) + 0.25 * max(0, math.cos(b)))
            r[(f"wing1.{side}", "rotation")] = euler(z=s * 0.05 * math.sin(2 * ph))
        return r

    def flap(ph):
        c = math.sin(ph)
        r = {
            ("hips", "translation"): rest_t("hips") + np.array([0, -0.012 * c, 0]),
            ("chest", "rotation"): euler(x=0.04 * c),
            ("head", "rotation"): euler(x=-0.05 * c),
        }
        for i in range(1, 6):
            r[(f"tail{i}", "rotation")] = euler(x=0.05 * math.sin(ph - i * 0.5))
        for side, s in (("L", 1), ("R", -1)):
            r[(f"wing1.{side}", "rotation")] = euler(z=s * 0.75 * c, y=s * 0.1 * math.cos(ph))
            r[(f"wing2.{side}", "rotation")] = euler(z=s * 0.35 * math.sin(ph - 0.5))
            for f in (1, 2, 3):
                r[(f"finger{f}.{side}", "rotation")] = euler(z=s * 0.25 * math.sin(ph - 0.9 - 0.1 * f))
        return r

    def roar(ph):
        # one-shot shaped as 0 -> peak -> 0 over the clip
        e = (1 - math.cos(ph)) / 2
        shake = 0.03 * math.sin(ph * 9) * e
        r = {
            ("chest", "rotation"): euler(x=-0.10 * e),
            ("neck", "rotation"): euler(x=-0.18 * e),
            ("neck2", "rotation"): euler(x=-0.10 * e),
            ("head", "rotation"): euler(x=0.12 * e, y=shake),
            ("jaw", "rotation"): euler(x=0.55 * e),
        }
        for side, s in (("L", 1), ("R", -1)):
            r[(f"wing1.{side}", "rotation")] = euler(z=s * 0.45 * e)
            r[(f"wing2.{side}", "rotation")] = euler(z=s * 0.15 * e)
        for i in range(1, 6):
            r[(f"tail{i}", "rotation")] = euler(x=-0.05 * e, y=0.05 * math.sin(ph * 3) * e)
        return r

    clips["Idle"] = clip(3.0, idle)
    clips["Walk"] = clip(1.0, walk)
    clips["Flap"] = clip(0.6, flap)
    clips["Roar"] = clip(1.6, roar)
    return clips


# ---------------------------------------------------------------------------
# GLB writer
# ---------------------------------------------------------------------------


class GLB:
    def __init__(self):
        self.bin = bytearray()
        self.gltf = {"asset": {"version": "2.0", "generator": "build_dragon_whelp.py"},
                     "buffers": [], "bufferViews": [], "accessors": []}

    def view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin += data
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            bv["target"] = target
        self.gltf["bufferViews"].append(bv)
        return len(self.gltf["bufferViews"]) - 1

    def accessor(self, arr, ctype, atype, target=None, normalized=False, minmax=False):
        arr = np.ascontiguousarray(arr)
        v = self.view(arr.tobytes(), target)
        count = arr.shape[0]
        acc = {"bufferView": v, "componentType": ctype, "count": int(count), "type": atype}
        if normalized:
            acc["normalized"] = True
        if minmax:
            a2 = arr.reshape(count, -1)
            acc["min"] = [float(x) for x in a2.min(0)]
            acc["max"] = [float(x) for x in a2.max(0)]
        self.gltf["accessors"].append(acc)
        return len(self.gltf["accessors"]) - 1

    def write(self, path):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.gltf["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(self.gltf, separators=(",", ":")).encode()
        while len(js) % 4:
            js += b" "
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A))
            f.write(js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942))
            f.write(self.bin)


FLOAT, UBYTE, USHORT, UINT = 5126, 5121, 5123, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


def build(out_path, tex_size):
    build_body()
    build_head()
    build_spine_plates()
    build_legs()
    build_wings()

    P, N, UV, C, J, Wt, T = [], [], [], [], [], [], []
    base = 0
    for part in PARTS:
        nrm = smooth_normals(part.pos, part.tri)
        j, w = compute_weights(part)
        col = paint_light(part.col, nrm, part.pos, part)
        P.append(part.pos)
        N.append(nrm)
        UV.append(part.uv)
        C.append(col)
        J.append(j)
        Wt.append(w)
        T.append(part.tri + base)
        base += len(part.pos)
    P = np.vstack(P).astype(np.float32)
    N = np.vstack(N).astype(np.float32)
    UV = np.vstack(UV).astype(np.float32)
    C = np.vstack(C)
    J = np.vstack(J).astype(np.uint8)
    Wt = np.vstack(Wt).astype(np.float32)
    T = np.vstack(T)
    # drop degenerate triangles (from flattened paws / collapsed poles)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    T = T[area > 1e-10]
    assert len(P) < 65536, "too many vertices for 16-bit indices"
    Wt = Wt / Wt.sum(1, keepdims=True)

    lin = srgb_to_linear(np.clip(C, 0, 1))
    C8 = np.concatenate([np.round(lin * 255), np.full((len(lin), 1), 255)], 1).astype(np.uint8)

    g = GLB()
    acc_pos = g.accessor(P, FLOAT, "VEC3", ARRAY_BUFFER, minmax=True)
    acc_nrm = g.accessor(N, FLOAT, "VEC3", ARRAY_BUFFER)
    acc_uv = g.accessor(UV, FLOAT, "VEC2", ARRAY_BUFFER)
    acc_col = g.accessor(C8, UBYTE, "VEC4", ARRAY_BUFFER, normalized=True)
    acc_j = g.accessor(J, UBYTE, "VEC4", ARRAY_BUFFER)
    acc_w = g.accessor(Wt, FLOAT, "VEC4", ARRAY_BUFFER)
    acc_idx = g.accessor(T.reshape(-1).astype(np.uint16), USHORT, "SCALAR", ELEMENT_ARRAY_BUFFER)

    # texture
    tex = paint_texture(tex_size)
    buf = io.BytesIO()
    tex.save(buf, "PNG", optimize=True)
    img_view = g.view(buf.getvalue())
    tex.save(out_path.rsplit(".", 1)[0] + "_albedo.png")

    gl = g.gltf
    gl["images"] = [{"bufferView": img_view, "mimeType": "image/png", "name": "dragon_whelp_albedo"}]
    gl["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 33071}]
    gl["textures"] = [{"sampler": 0, "source": 0}]
    gl["materials"] = [{
        "name": "DragonWhelp",
        "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0,
                                 "roughnessFactor": 0.82},
    }]
    gl["meshes"] = [{"name": "DragonWhelp", "primitives": [{
        "attributes": {"POSITION": acc_pos, "NORMAL": acc_nrm, "TEXCOORD_0": acc_uv,
                       "COLOR_0": acc_col, "JOINTS_0": acc_j, "WEIGHTS_0": acc_w},
        "indices": acc_idx, "material": 0, "mode": 4}]}]

    # nodes: 0 = skinned mesh (kept at the scene root, as the spec asks), 1.. = joints
    nodes = [{"name": "DragonWhelp", "mesh": 0, "skin": 0}]
    joint_node = {}
    for i, b in enumerate(BONES):
        joint_node[b["name"]] = 1 + i
    for b in BONES:
        parent = b["parent"]
        t = b["head"] - (B(parent)["head"] if parent else 0)
        nd = {"name": b["name"], "translation": [float(x) for x in t]}
        kids = [joint_node[c["name"]] for c in BONES if c["parent"] == b["name"]]
        if kids:
            nd["children"] = kids
        nodes.append(nd)
    gl["nodes"] = nodes
    gl["scenes"] = [{"name": "Scene", "nodes": [0, joint_node["root"]]}]
    gl["scene"] = 0

    ibm = np.zeros((len(BONES), 4, 4), np.float32)
    for i, b in enumerate(BONES):
        m = np.eye(4)
        m[:3, 3] = -b["head"]
        ibm[i] = m.T  # column-major
    acc_ibm = g.accessor(ibm.reshape(len(BONES), 16), FLOAT, "MAT4")
    gl["skins"] = [{"name": "DragonWhelp_Rig", "inverseBindMatrices": acc_ibm,
                    "joints": [joint_node[b["name"]] for b in BONES],
                    "skeleton": joint_node["root"]}]

    anims = []
    for name, tracks in build_animations().items():
        samplers, channels = [], []
        time_acc = {}
        for (jn, path), (times, values) in tracks.items():
            key = len(times)
            if key not in time_acc:
                time_acc[key] = g.accessor(times.astype(np.float32), FLOAT, "SCALAR", minmax=True)
            vals = values.astype(np.float32)
            if path == "rotation":
                # keep quaternion hemisphere continuous
                for i in range(1, len(vals)):
                    if np.dot(vals[i], vals[i - 1]) < 0:
                        vals[i] = -vals[i]
            out = g.accessor(vals, FLOAT, "VEC4" if path == "rotation" else "VEC3")
            samplers.append({"input": time_acc[key], "output": out, "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1,
                             "target": {"node": joint_node[jn], "path": path}})
        anims.append({"name": name, "samplers": samplers, "channels": channels})
    gl["animations"] = anims

    g.write(out_path)
    return dict(vertices=len(P), triangles=len(T), joints=len(BONES),
                animations=[a["name"] for a in anims],
                bounds=(P.min(0).round(3).tolist(), P.max(0).round(3).tolist()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="dragon_whelp.glb")
    ap.add_argument("--texture-size", type=int, default=512, choices=(256, 512, 1024, 2048))
    args = ap.parse_args()
    stats = build(args.output, args.texture_size)
    print(f"wrote {args.output}")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
