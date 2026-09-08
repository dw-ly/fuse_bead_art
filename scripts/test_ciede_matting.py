#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for CIEDE2000 + background matting."""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
from photo2beads import delta_e76, delta_e2000, srgb_to_lab, process
from matting import apply_matting, corner_flood

OUT = os.path.join(os.path.dirname(__file__), '..', 'examples', '_synth')
os.makedirs(OUT, exist_ok=True)


def test_ciede_identical():
    lab = np.array([50.0, 10.0, -5.0])
    d = float(delta_e2000(lab, lab))
    assert d < 1e-6, d
    print(f'[OK] CIEDE2000 identical Lab → {d:.2e}')


def test_ciede_known_pair_ballpark():
    # sRGB blue vs red — ΔE2000 typically ~ dozens
    blue = srgb_to_lab(np.array([0, 0, 255], dtype=np.uint8))
    red = srgb_to_lab(np.array([255, 0, 0], dtype=np.uint8))
    d = float(delta_e2000(blue, red))
    assert 20 < d < 100, d
    print(f'[OK] blue vs red ΔE2000={d:.1f} (ballpark 20–100)')


def test_e2000_ne_e76_skin_green():
    skin = srgb_to_lab(np.array([224, 172, 145], dtype=np.uint8))
    green = srgb_to_lab(np.array([40, 160, 70], dtype=np.uint8))
    e76 = float(delta_e76(skin, green))
    e2 = float(delta_e2000(skin, green))
    assert abs(e76 - e2) > 0.5, (e76, e2)
    print(f'[OK] skin vs green e76={e76:.1f} e2000={e2:.1f} (不等)')


def test_matting_red_bg_blue_circle():
    size = 160
    img = Image.new('RGB', (size, size), (220, 40, 40))
    d = ImageDraw.Draw(img)
    d.ellipse([40, 40, 120, 120], fill=(40, 80, 220))
    path = os.path.join(OUT, 'matting_synth.png')
    img.save(path)
    rgba, used = apply_matting(img, mode='corner', as_rgba=True)
    assert used.startswith('corner'), used
    arr = np.asarray(rgba)
    # corners transparent
    assert arr[2, 2, 3] < 128, arr[2, 2, 3]
    assert arr[2, -3, 3] < 128
    assert arr[-3, 2, 3] < 128
    # center kept
    cy = cx = size // 2
    assert arr[cy, cx, 3] >= 128, arr[cy, cx, 3]
    assert arr[cy, cx, 2] > 150  # blue-ish
    rgba.save(os.path.join(OUT, 'matting_synth_out.png'))
    print(f'[OK] matting corner_flood center kept, corners alpha=0 (mode={used})')


def test_process_matting_empty_cells():
    path = os.path.join(OUT, 'matting_synth.png')
    if not os.path.exists(path):
        test_matting_red_bg_blue_circle()
    out = os.path.join(OUT, 'matting_beads')
    grid, counts, avg = process(
        path, 29, 'mard291', 'nearest', 8, None, out, 12, 42,
        preset='通用', metric='e2000', matting=True, matting_mode='corner')
    empty = int((grid < 0).sum())
    assert empty > 50, empty
    assert all(c[0] != '' for c in counts)
    print(f'[OK] process+matting empty={empty} unique={len(counts)} avgΔE={avg:.1f}')


def test_delta_cli_default_wired():
    # smoke: e76 path
    path = os.path.join(OUT, 'matting_synth.png')
    out = os.path.join(OUT, 'matting_e76')
    grid, _, avg = process(
        path, 16, 'hama', 'nearest', 4, None, out, 10, 42,
        preset='通用', metric='e76', matting=False)
    assert grid.min() >= 0
    print(f'[OK] e76 path avgΔE={avg:.1f}')


if __name__ == '__main__':
    test_ciede_identical()
    test_ciede_known_pair_ballpark()
    test_e2000_ne_e76_skin_green()
    test_matting_red_bg_blue_circle()
    test_process_matting_empty_cells()
    test_delta_cli_default_wired()
    print('\nAll CIEDE/matting tests passed.')
