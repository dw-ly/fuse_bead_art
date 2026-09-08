#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-ish tests for suggest_grid + cartoon rewrite."""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
from enhance import cartoon, apply_preset
from photo2beads import suggest_grid, resize_for_beads

OUT = os.path.join(os.path.dirname(__file__), '..', 'examples', '_synth')
os.makedirs(OUT, exist_ok=True)


def make_synth(path, size=200):
    """简单合成图：大色块脸 + 背景，便于量化。"""
    img = Image.new('RGB', (size, size), (180, 210, 240))
    d = ImageDraw.Draw(img)
    d.ellipse([50, 40, 150, 160], fill=(240, 190, 160))
    d.ellipse([75, 80, 90, 95], fill=(40, 40, 50))
    d.ellipse([110, 80, 125, 95], fill=(40, 40, 50))
    d.arc([80, 100, 120, 130], 20, 160, fill=(180, 60, 60), width=3)
    d.rectangle([55, 35, 145, 55], fill=(60, 40, 30))
    img.save(path)
    return path


def test_suggest_grid():
    path = os.path.join(OUT, 'portrait_synth.png')
    make_synth(path)
    rows, rec, floor = suggest_grid(
        path, 'mard291', 'kmeans', 12, None, 42, '人像', 60)
    assert floor == 49, floor
    assert rec in [r['N'] for r in rows], rec
    assert all(r['N'] <= 60 for r in rows)
    assert all(r['beads'] == r['N'] * r['N'] for r in rows)
    print(f'[OK] suggest_grid floor={floor} recommended={rec} rows={[(r["N"], round(r["avg_de"],1)) for r in rows]}')
    return rec


def test_cartoon_same_size_and_outline():
    path = os.path.join(OUT, 'portrait_synth.png')
    if not os.path.exists(path):
        make_synth(path)
    img = Image.open(path).convert('RGB')
    out = cartoon(img, levels=8, outline_strength=1.0)
    assert out.size == img.size, (out.size, img.size)
    arr_out = np.asarray(out)
    dark = (arr_out[..., 0] < 40) & (arr_out[..., 1] < 40) & (arr_out[..., 2] < 40)
    n_dark = int(dark.sum())
    assert n_dark > 50, f'expected dark outline pixels, got {n_dark}'
    mean_lum = arr_out.mean()
    assert mean_lum > 40, f'too dark overall ({mean_lum}), possible AND holes'
    out_path = os.path.join(OUT, 'portrait_synth_cartoon.png')
    out.save(out_path)
    print(f'[OK] cartoon size={out.size} dark_px={n_dark} mean_lum={mean_lum:.1f} -> {out_path}')


def test_cartoon_no_outline():
    img = Image.new('RGB', (64, 64), (200, 100, 80))
    out = cartoon(img, levels=6, outline_strength=0)
    assert out.size == (64, 64)
    print('[OK] cartoon outline_strength=0')


def test_resize_box_down():
    img = Image.new('RGB', (200, 200), (100, 150, 200))
    small = resize_for_beads(img, 29)
    assert small.size == (29, 29)
    big = resize_for_beads(Image.new('RGB', (10, 10), (1, 2, 3)), 29)
    assert big.size == (29, 29)
    print('[OK] resize_for_beads BOX down / LANCZOS up')


def test_apply_preset_cartoon():
    path = os.path.join(OUT, 'portrait_synth.png')
    img = Image.open(path).convert('RGB')
    out = apply_preset(img, '人像转插画')
    assert out.size[0] == out.size[1]
    out.save(os.path.join(OUT, 'portrait_synth_preset.png'))
    print(f'[OK] apply_preset 人像转插画 -> {out.size}')


if __name__ == '__main__':
    test_resize_box_down()
    test_suggest_grid()
    test_cartoon_same_size_and_outline()
    test_cartoon_no_outline()
    test_apply_preset_cartoon()
    print('\nAll tests passed.')
