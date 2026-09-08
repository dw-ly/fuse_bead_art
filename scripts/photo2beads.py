#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
photo2beads.py — 照片 → 拼豆图纸（M1 原型）

管线：可选抠图 → 预设增强 → 缩到 N×N → 量化到豆色（默认 CIEDE2000）→ 输出图纸 + 用量清单

依赖：Pillow、numpy（轻量，可离线安装）

用法示例：
    python scripts/photo2beads.py 照片.jpg -N 49                 # 默认: MARD 291 色板, k-means 主色
    python scripts/photo2beads.py 照片.jpg -N 39 -p hama -m nearest
    python scripts/photo2beads.py 照片.jpg --suggest-grid --preset 人像   # 扫描推荐最小网格
    python scripts/photo2beads.py 照片.jpg --apply-suggest --preset 人像  # 用推荐 N 出图
    python scripts/photo2beads.py 照片.jpg -N 49 -k 20 --only A1,B2,F3 -o 我的图纸

生成文件（默认以输入文件名为前缀）：
    {out}_preview.png   圆角豆粒风格的预览图（照成品效果）
    {out}_spec.png      带色号/图例的施工图（打印对照用）
    {out}_usage.csv     各色号用量统计（配豆对账用）
"""
import argparse
import csv
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from enhance import PRESETS, PRESET_GRID_FLOOR, apply_preset
from matting import apply_matting

# 色号库路径（项目数据资产，由 parse_palette.py 生成）
PALETTE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "bead_palettes.json")
MAX_GRID_HARD = 100  # 网格物理上限（细节密集的小图需 80-100 才能干净分离特征）

BRANDS = ["mard291", "mard221", "artkal", "perler", "hama", "artkalMini"]


# ---------------------------------------------------------------- 颜色数学
def srgb_to_lab(rgb):
    """sRGB(0-255, uint8) -> CIELAB(D65)。输入 shape (...,3)。"""
    rgb = np.asarray(rgb, dtype=np.float64) / 255.0

    def lin(c):
        return np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)

    r, g, b = lin(rgb[..., 0]), lin(rgb[..., 1]), lin(rgb[..., 2])
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    Xn, Yn, Zn = 0.95047, 1.0, 1.08883
    eps, kap = 216 / 24389, 24389 / 27

    def f(t):
        return np.where(t > eps, np.cbrt(t), (kap * t + 16) / 116)

    fx, fy, fz = f(x / Xn), f(y / Yn), f(z / Zn)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b = 200 * (fy - fz)
    return np.stack([L, a, b], axis=-1)


def delta_e76(a, b):
    """CIELAB 两两色差 ΔE76，a/b 同 shape 或可广播。"""
    return np.sqrt(np.sum((a - b) ** 2, axis=-1))


def delta_e2000(lab1, lab2, kL=1.0, kC=1.0, kH=1.0):
    """CIEDE2000 色差（Sharma et al.）。支持广播，末维为 Lab。"""
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    C1 = np.sqrt(a1 * a1 + b1 * b1)
    C2 = np.sqrt(a2 * a2 + b2 * b2)
    Cbar = 0.5 * (C1 + C2)
    Cbar7 = Cbar ** 7
    G = 0.5 * (1.0 - np.sqrt(Cbar7 / (Cbar7 + 25.0 ** 7)))
    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2
    C1p = np.sqrt(a1p * a1p + b1 * b1)
    C2p = np.sqrt(a2p * a2p + b2 * b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    dLp = L2 - L1
    dCp = C2p - C1p
    dhp = h2p - h1p
    dhp = np.where((C1p * C2p) == 0, 0.0, dhp)
    dhp = np.where(dhp > 180, dhp - 360, dhp)
    dhp = np.where(dhp < -180, dhp + 360, dhp)
    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp) / 2.0)
    Lbar = 0.5 * (L1 + L2)
    Cbarp = 0.5 * (C1p + C2p)
    hsum = h1p + h2p
    hbar = np.where((C1p * C2p) == 0, hsum, hsum)
    hbar = np.where((np.abs(h1p - h2p) > 180) & (hsum < 360), (hsum + 360) / 2.0, hbar)
    hbar = np.where((np.abs(h1p - h2p) > 180) & (hsum >= 360), (hsum - 360) / 2.0, hbar)
    hbar = np.where(np.abs(h1p - h2p) <= 180, hsum / 2.0, hbar)
    T = (1.0 - 0.17 * np.cos(np.radians(hbar - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * hbar))
         + 0.32 * np.cos(np.radians(3.0 * hbar + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * hbar - 63.0)))
    dRo = 30.0 * np.exp(-((hbar - 275.0) / 25.0) ** 2)
    Cbarp7 = Cbarp ** 7
    RC = 2.0 * np.sqrt(Cbarp7 / (Cbarp7 + 25.0 ** 7))
    SL = 1.0 + (0.015 * (Lbar - 50.0) ** 2) / np.sqrt(20.0 + (Lbar - 50.0) ** 2)
    SC = 1.0 + 0.045 * Cbarp
    SH = 1.0 + 0.015 * Cbarp * T
    RT = -np.sin(np.radians(2.0 * dRo)) * RC
    return np.sqrt(
        (dLp / (kL * SL)) ** 2
        + (dCp / (kC * SC)) ** 2
        + (dHp / (kH * SH)) ** 2
        + RT * (dCp / (kC * SC)) * (dHp / (kH * SH))
    )


def delta_e(a, b, metric="e2000"):
    """统一入口：metric in {e76, e2000}。"""
    if metric == "e76":
        return delta_e76(a, b)
    return delta_e2000(a, b)


# ---------------------------------------------------------------- 色板
def load_palette(brand, only=None):
    """读取色板 -> [(code, hex), ...]。only: 逗号分隔的色号子集（不填=全色板）。"""
    with open(PALETTE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    series = data[brand]
    colors = [tuple(c) for s in series.values() for c in s["colors"]]
    if only:
        wanted = {c.strip().upper() for c in only.split(",")}
        colors = [c for c in colors if c[0].upper() in wanted]
        if not colors:
            print(f"[警告] 子集 {only} 在 {brand} 中没有匹配色号，回退到全色板。", file=sys.stderr)
            colors = [tuple(c) for s in series.values() for c in s["colors"]]
    return colors


# ---------------------------------------------------------------- 量化
def quantize_nearest(lab_img, pal_lab, metric="e2000", alpha=None):
    """方案A：每个格子找色差最近豆色。alpha<128 → -1（空白不拼）。"""
    flat = lab_img.reshape(-1, 3)
    if metric == "e76":
        d = np.sum((flat[:, None, :] - pal_lab[None, :, :]) ** 2, axis=-1)
        idx = d.argmin(axis=-1)
    else:
        # 分批避免超大内存：每批像素
        batch = 4096
        parts = []
        for i in range(0, len(flat), batch):
            chunk = flat[i:i + batch]
            d = delta_e2000(chunk[:, None, :], pal_lab[None, :, :])
            parts.append(d.argmin(axis=-1))
        idx = np.concatenate(parts)
    grid = idx.reshape(lab_img.shape[:2]).astype(np.int32)
    if alpha is not None:
        a = np.asarray(alpha).reshape(lab_img.shape[:2])
        grid = grid.copy()
        grid[a < 128] = -1
    return grid


def quantize_kmeans(lab_img, pal_lab, k, seed, metric="e2000", alpha=None):
    """方案B：k-means 主色聚类，再映射每个主色到最近豆色（照片推荐）。
    簇内距离仍用欧氏（稳定快）；簇→色板用 metric。
    """
    flat = lab_img.reshape(-1, 3).astype(np.float64)
    a_flat = None
    if alpha is not None:
        a_flat = np.asarray(alpha).reshape(-1)
        valid = a_flat >= 128
        if not valid.any():
            return np.full(lab_img.shape[:2], -1, dtype=np.int32)
        work = flat[valid]
    else:
        valid = None
        work = flat
    rng = np.random.default_rng(seed)
    kk = min(k, len(work))
    centers = work[rng.choice(len(work), kk, replace=False)].copy()
    for _ in range(30):
        d = np.sum((work[:, None, :] - centers[None, :, :]) ** 2, axis=-1)
        labels = d.argmin(axis=-1)
        new_centers = centers.copy()
        for i in range(kk):
            m = labels == i
            if m.any():
                new_centers[i] = work[m].mean(axis=0)
        if np.allclose(new_centers, centers):
            centers = new_centers
            break
        centers = new_centers
    # 每个主色映射到最近豆色
    if metric == "e76":
        cd = np.sum((centers[:, None, :] - pal_lab[None, :, :]) ** 2, axis=-1)
        center_bead = cd.argmin(axis=-1)
    else:
        cd = delta_e2000(centers[:, None, :], pal_lab[None, :, :])
        center_bead = cd.argmin(axis=-1)
    mapped = center_bead[labels]
    if valid is None:
        return mapped.reshape(lab_img.shape[:2]).astype(np.int32)
    out = np.full(flat.shape[0], -1, dtype=np.int32)
    out[valid] = mapped
    return out.reshape(lab_img.shape[:2])


# ---------------------------------------------------------------- 像素级后处理
def luminance_hex(hexc):
    r, g, b = int(hexc[1:3], 16), int(hexc[3:5], 16), int(hexc[5:7], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def clean_isolated(grid):
    """去孤立杂点：只清"嵌在实心区里的散点"——周围 8 格无同色，且某一邻域色占绝对多数(≥半)。
    保护线条/纹理/过渡色；跳过空白格(-1)。"""
    n = grid.shape[0]
    out = grid.copy()
    for y in range(n):
        for x in range(n):
            center = grid[y, x]
            if center < 0:
                continue
            y0, y1 = max(0, y - 1), min(n - 1, y + 1)
            x0, x1 = max(0, x - 1), min(n - 1, x + 1)
            nb = grid[y0:y1 + 1, x0:x1 + 1]
            if nb.size <= 1:
                continue
            if (nb != center).sum() == nb.size - 1:  # 所有邻域都不同色 → 候选孤立
                pos = nb[nb >= 0]
                if pos.size == 0:
                    continue
                vals, cnts = np.unique(pos, return_counts=True)
                if int(cnts.max()) >= max(3, nb.size // 2):  # 邻域主色占多数才替换(保护线条)
                    out[y, x] = vals[int(np.argmax(cnts))]
    return out


def add_outline(grid, palette, threshold=45):
    """卡通描边：4 邻域明暗差超过阈值 → 涂成色板最深色（形成轮廓线）。跳过空白格。"""
    n = grid.shape[0]
    lums = np.array([luminance_hex(c[1]) for c in palette])
    dark = int(np.argmin(lums))
    out = grid.copy()
    for y in range(n):
        for x in range(n):
            if grid[y, x] < 0:
                continue
            L = lums[grid[y, x]]
            md = 0.0
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < n and 0 <= nx < n and grid[ny, nx] >= 0:
                    md = max(md, abs(L - lums[grid[ny, nx]]))
            if md > threshold:
                out[y, x] = dark
    return out


# ---------------------------------------------------------------- 绘图
def _draw_checker(d, x0, y0, cell, sq=None):
    """空白格棋盘底。"""
    sq = sq or max(2, cell // 4)
    for yy in range(0, cell, sq):
        for xx in range(0, cell, sq):
            lite = ((xx // sq) + (yy // sq)) % 2 == 0
            fill = (235, 235, 235) if lite else (255, 255, 255)
            d.rectangle([x0 + xx, y0 + yy, x0 + min(xx + sq, cell) - 1, y0 + min(yy + sq, cell) - 1], fill=fill)


def draw_preview(grid, palette, cell, labels=False):
    """圆角豆粒风格预览图，接近成品观感。labels=True 时给每颗豆标注色号。空白格(-1)画棋盘。"""
    n = grid.shape[0]
    gap = max(2, cell // 8)
    pad = gap
    size = n * cell + gap * (n - 1) + 2 * pad
    img = Image.new("RGB", (size, size), (245, 245, 245))
    d = ImageDraw.Draw(img)
    radius = cell * 0.22
    label_font = ImageFont.load_default(size=max(8, cell // 4)) if labels else None
    for r in range(n):
        for c in range(n):
            x0 = pad + c * (cell + gap)
            y0 = pad + r * (cell + gap)
            idx = int(grid[r, c])
            if idx < 0:
                _draw_checker(d, x0, y0, cell)
                if labels:
                    code = "空"
                    tw = d.textlength(code, font=label_font)
                    d.text((x0 + (cell - tw) / 2, y0 + (cell - label_font.size) / 2), code,
                           fill=(120, 120, 120), font=label_font)
                continue
            hexc = palette[idx][1]
            d.rounded_rectangle([x0, y0, x0 + cell, y0 + cell], radius=radius, fill=hexc)
            if labels:
                code = palette[idx][0]
                tw = d.textlength(code, font=label_font)
                d.text((x0 + (cell - tw) / 2, y0 + (cell - label_font.size) / 2), code,
                       fill=_text_color(hexc), font=label_font)
    return img


def _text_color(hexc):
    """根据色块明暗选择可读的文字颜色。"""
    r = int(hexc[1:3], 16)
    g = int(hexc[3:5], 16)
    b = int(hexc[5:7], 16)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return (20, 20, 20) if lum > 150 else (255, 255, 255)


def draw_spec(grid, palette, counts):
    """施工图：平铺色块 + 色号标注 + 边缘坐标刻度 + 底部用量图例。"""
    n = grid.shape[0]
    # 格子大小自适应：网格越大格子越小，但保证色号可读
    cell = 48 if n <= 30 else (30 if n <= 49 else 26)
    gap = 2
    ruler = 16 if n >= 30 else 12  # 边缘坐标刻度区宽度
    grid_px = n * cell + gap * (n - 1)
    W = ruler * 2 + grid_px
    # 用量图例（按数量降序）
    legend_lines = [(code, hexc, cnt) for code, hexc, cnt in counts]
    legend_font = ImageFont.load_default(size=13)
    lh = 20
    legend_top = ruler + grid_px + 24
    img = Image.new("RGB", (W, legend_top + lh * (len(legend_lines) + 1)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    # 网格
    label_font = ImageFont.load_default(size=max(9, cell // 4))
    for r in range(n):
        for c in range(n):
            x0 = ruler + c * (cell + gap)
            y0 = ruler + r * (cell + gap)
            idx = int(grid[r, c])
            if idx < 0:
                _draw_checker(d, x0, y0, cell)
                d.rectangle([x0, y0, x0 + cell, y0 + cell], outline=(160, 160, 160), width=1)
                code = "空"
                tw = d.textlength(code, font=label_font)
                d.text((x0 + (cell - tw) / 2, y0 + (cell - label_font.size) / 2), code,
                       fill=(120, 120, 120), font=label_font)
                continue
            hexc = palette[idx][1]
            d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=hexc, outline=(60, 60, 60), width=1)
            # 色号标注 + 自适应文字颜色
            code = palette[idx][0]
            tw = d.textlength(code, font=label_font)
            d.text((x0 + (cell - tw) / 2, y0 + (cell - label_font.size) / 2), code,
                   fill=_text_color(hexc), font=label_font)
    # 边缘坐标刻度（每 5 格标数字，方便数豆）
    ruler_font = ImageFont.load_default(size=11)
    for i in range(0, n, 5):
        tx = ruler + i * (cell + gap) + cell / 2
        d.text((tx - d.textlength(str(i), font=ruler_font) / 2, ruler - 12), str(i),
               fill=(60, 60, 60), font=ruler_font)
        ty = ruler + i * (cell + gap) + cell / 2
        d.text((ruler - d.textlength(str(i), font=ruler_font) - 2, ty - 6), str(i),
               fill=(60, 60, 60), font=ruler_font)
    # 图例
    bead_total = sum(cnt for _, _, cnt in counts)
    empty_n = int((grid < 0).sum()) if hasattr(grid, 'shape') else 0
    empty_note = f"，空白不拼 {empty_n}" if empty_n else ""
    d.text((ruler, legend_top - 16), f"用量清单（共 {bead_total} 颗豆{empty_note}）",
           fill=(30, 30, 30), font=legend_font)
    for i, (code, hexc, cnt) in enumerate(legend_lines):
        y = legend_top + i * lh
        d.rectangle([ruler, y + 3, ruler + 16, y + 17], fill=hexc, outline=(0, 0, 0))
        d.text((ruler + 22, y), f"{code}  {hexc}  ×{cnt}", fill=(30, 30, 30), font=legend_font)
    return img



# ---------------------------------------------------------------- 网格建议 / 缩小
DEFAULT_GRID_CANDIDATES = [29, 39, 49, 59, 60]
AVG_DE_THRESHOLD = 15.0


def resize_for_beads(img, n):
    """缩小到 n×n：大图用 BOX/AREA（面积平均，抗混叠）；放大或等大用 LANCZOS。

    照片路径缩小时 BOX 比 LANCZOS 更能代表局部均值，减少抽样噪点；
    放大仍用 LANCZOS 保边缘。
    """
    w, h = img.size
    if n < min(w, h):
        # Pillow 10+ 有 Image.Resampling.BOX；旧版 Image.BOX
        box = getattr(Image, "BOX", None) or getattr(getattr(Image, "Resampling", None), "BOX", Image.LANCZOS)
        return img.resize((n, n), box)
    return img.resize((n, n), Image.LANCZOS)


def evaluate_grid(img_enhanced, n, palette, pal_lab, method, k, seed, metric="e2000"):
    """对已增强方形图评估某一 N：量化后返回 avgΔE / unique / beads。"""
    small = resize_for_beads(img_enhanced.convert("RGBA") if img_enhanced.mode == "RGBA" else img_enhanced, n)
    arr = np.asarray(small)
    if arr.shape[-1] == 4:
        rgb, alpha = arr[..., :3], arr[..., 3]
    else:
        rgb, alpha = arr, None
    lab_img = srgb_to_lab(rgb)
    if method == "nearest":
        grid = quantize_nearest(lab_img, pal_lab, metric=metric, alpha=alpha)
    else:
        kk = min(k, min(n * n, len(palette)))
        grid = quantize_kmeans(lab_img, pal_lab, kk, seed, metric=metric, alpha=alpha)
    mask = grid >= 0
    if mask.any():
        avg_de = float(delta_e(lab_img[mask], pal_lab[grid[mask]], metric).mean())
    else:
        avg_de = 0.0
    unique = int(len(np.unique(grid[mask]))) if mask.any() else 0
    beads = int(mask.sum())
    return {
        "N": n,
        "beads": beads,
        "avg_de": avg_de,
        "unique": unique,
        "pass": avg_de <= AVG_DE_THRESHOLD,
        "empty": int((~mask).sum()) if alpha is not None else 0,
    }


def suggest_grid(image_path, brand, method, k, only, seed, preset, max_grid,
                 candidates=None, cartoon_levels=10, metric="e2000",
                 matting=False, matting_mode="auto"):
    """扫描候选网格，返回 (rows, recommended_N, floor)。

    推荐规则：最小 N ≥ 主体下限 且 avgΔE ≤ 15；若无一通过则取下限以上 ΔE 最低者。
    """
    if candidates is None:
        candidates = DEFAULT_GRID_CANDIDATES
    max_grid = min(max_grid, MAX_GRID_HARD)
    cands = sorted({n for n in candidates if 1 <= n <= max_grid})
    if not cands:
        cands = [min(49, max_grid)]

    floor = PRESET_GRID_FLOOR.get(preset, 29)
    floor = min(floor, max_grid)

    img0 = Image.open(image_path).convert("RGB")
    src_size = img0.size
    steps = []
    img_rgb, alpha, _ = _prepare_with_matting(img0, matting, matting_mode, steps)
    img = apply_preset(img_rgb, preset, cartoon_levels=cartoon_levels)
    alpha = _align_alpha_after_preset(alpha, src_size, img)
    if alpha is not None:
        img = Image.merge("RGBA", (*img.split(), alpha))
    palette = load_palette(brand, only)
    pal_rgb = np.array([list(bytes.fromhex(c[1][1:])) for c in palette], dtype=np.uint8)
    pal_lab = srgb_to_lab(pal_rgb)

    rows = [evaluate_grid(img, n, palette, pal_lab, method, k, seed, metric=metric) for n in cands]

    eligible = [r for r in rows if r["N"] >= floor and r["pass"]]
    if eligible:
        recommended = min(eligible, key=lambda r: r["N"])["N"]
    else:
        above = [r for r in rows if r["N"] >= floor] or rows
        recommended = min(above, key=lambda r: (r["avg_de"], r["N"]))["N"]
    return rows, recommended, floor


def print_suggest_table(rows, recommended, floor, preset):
    print(f"主体下限 floor={floor}（预设「{preset}」）｜阈值 avgΔE ≤ {AVG_DE_THRESHOLD}")
    print(f"{'N':>4}  {'豆量':>6}  {'用色':>4}  {'avgΔE':>7}  判定")
    print("-" * 40)
    for r in rows:
        mark = "✓" if r["pass"] else "·"
        star = " ←推荐" if r["N"] == recommended else ""
        floor_tag = " [≥floor]" if r["N"] >= floor else ""
        print(f"{r['N']:>4}  {r['beads']:>6}  {r['unique']:>4}  {r['avg_de']:>7.1f}  {mark}{floor_tag}{star}")
    print(f"推荐网格: {recommended}×{recommended}")
    return recommended


def _prepare_with_matting(img_rgb, matting, matting_mode, steps):
    """matting → RGBA；返回 (rgb_for_enhance: RGB, alpha_L: PIL L or None, mode_used)."""
    if not matting:
        return img_rgb, None, None
    rgba, used = apply_matting(img_rgb, mode=matting_mode, as_rgba=True)
    steps.append((f"背景抠图({used})", False))
    arr = np.asarray(rgba)
    alpha = Image.fromarray(arr[..., 3], "L")
    rgb = arr[..., :3].copy()
    rgb[arr[..., 3] < 128] = 255  # 透明区填白再增强，避免污染
    return Image.fromarray(rgb, "RGB"), alpha, used


def _align_alpha_after_preset(alpha, src_size, out_img):
    """增强会居中裁方；对 alpha 做同样中心裁方再缩到 out 尺寸。"""
    if alpha is None:
        return None
    ow, oh = src_size
    side = min(ow, oh)
    left = (ow - side) // 2
    top = (oh - side) // 2
    a = alpha.crop((left, top, left + side, top + side))
    return a.resize(out_img.size, Image.NEAREST)


# ---------------------------------------------------------------- 主流程
def process(image_path, n, brand, method, k, only, out_prefix, cell, seed, labels=False, preset='通用',
            clean=False, outline=False, outline_threshold=45, cartoon_levels=10,
            metric="e2000", matting=False, matting_mode="auto"):
    # 顺序：matting → preset enhance → resize → quantize
    img0 = Image.open(image_path).convert("RGB")
    steps = []
    src_size = img0.size
    img_rgb, alpha, _mat_used = _prepare_with_matting(img0, matting, matting_mode, steps)
    img = apply_preset(img_rgb, preset, log=lambda m, is_err=False: steps.append((m, is_err)),
                       cartoon_levels=cartoon_levels)
    alpha = _align_alpha_after_preset(alpha, src_size, img)
    img = resize_for_beads(img, n)
    if alpha is not None:
        alpha = alpha.resize((n, n), Image.NEAREST)
        alpha_arr = np.asarray(alpha)
    else:
        alpha_arr = None
    rgb = np.asarray(img.convert("RGB"))  # (n, n, 3) uint8

    # 人像转插画：默认建议开启像素级描边（可被显式 --outline/--no-outline 覆盖）
    if outline is None:
        outline = (preset == '人像转插画')

    # 2. 色板
    palette = load_palette(brand, only)
    pal_rgb = np.array([list(bytes.fromhex(c[1][1:])) for c in palette], dtype=np.uint8)  # (K,3)
    pal_lab = srgb_to_lab(pal_rgb)
    lab_img = srgb_to_lab(rgb)

    # 3. 量化
    if method == "nearest":
        grid = quantize_nearest(lab_img, pal_lab, metric=metric, alpha=alpha_arr)
    else:
        k = min(k, min(n * n, len(palette)))
        grid = quantize_kmeans(lab_img, pal_lab, k, seed, metric=metric, alpha=alpha_arr)

    # 3.5 像素级后处理
    post_steps = []
    if clean:
        grid = clean_isolated(grid)
        post_steps.append("去孤立杂点")
    if outline:
        grid = add_outline(grid, palette, outline_threshold)
        post_steps.append(f"卡通描边(阈值{outline_threshold})")

    # 4. 统计与报告（空白不拼不计入用量）
    used = grid.ravel()
    empty_n = int((used < 0).sum())
    counts = []
    for i in range(len(palette)):
        c = int((used == i).sum())
        if c:
            counts.append((palette[i][0], palette[i][1], c))
    counts.sort(key=lambda x: -x[2])
    mask = grid >= 0
    if mask.any():
        avg_de = float(delta_e(lab_img[mask], pal_lab[grid[mask]], metric).mean())
    else:
        avg_de = 0.0
    unique = len(counts)
    bead_n = int(mask.sum())

    # 5. 输出
    preview_cell = max(cell, 28) if labels else cell
    draw_preview(grid, palette, preview_cell, labels=labels).save(f"{out_prefix}_preview.png")
    draw_spec(grid, palette, counts).save(f"{out_prefix}_spec.png")
    with open(f"{out_prefix}_usage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["color_code", "hex", "count"])
        w.writerows(counts)
        if empty_n:
            w.writerow(["EMPTY", "#透明/不拼", empty_n])

    metric_name = "CIEDE2000" if metric == "e2000" else "ΔE76"
    print(f"网格: {n}×{n} = {n * n} 格（实拼 {bead_n} 颗" + (f"，空白不拼 {empty_n}" if empty_n else "") +
          f"）  |  色板: {brand}（{len(palette)} 色可用，实际用 {unique} 色）")
    print(f"预设: {preset}" + (f" ｜ 处理: {'；'.join(m for m, e in steps if not e)}" if steps else ""))
    if post_steps:
        print("后处理: " + "、".join(post_steps))
    if any(e for _, e in steps):
        print("[警告] " + "；".join(m for m, e in steps if e))
    print(f"量化方法: {method}{'(k=' + str(k) + ')' if method == 'kmeans' else ''}  |  色差 {metric_name}  |  平均每豆色差 ΔE = {avg_de:.1f}")
    print(f"输出: {out_prefix}_preview.png / _spec.png / _usage.csv")
    if avg_de > 15 and outline:
        print(f"[提示] avgΔE={avg_de:.1f} 因卡通描边而偏高（描边是艺术化改动），属正常现象。")
    elif avg_de > 15:
        print(f"[警告] avgΔE={avg_de:.1f} 超过建议阈值 15，人像建议升一档网格（如 39→49）；简单图案可降档省豆。")
    else:
        print(f"[OK] avgΔE={avg_de:.1f} 在建议阈值 15 以内，此分辨率保真度可接受。")
    return grid, counts, avg_de


def main():
    ap = argparse.ArgumentParser(description="照片 → 拼豆图纸（M1 原型）")
    ap.add_argument("image", help="输入照片路径")
    ap.add_argument("-N", type=int, default=49, help=f"网格边长(豆数)，物理上限 {MAX_GRID_HARD}，默认 49")
    ap.add_argument("--max-grid", type=int, default=60,
                    help=f"网格上限（默认 60，细节密集的小图可调到 {MAX_GRID_HARD}），-N 超过上限会被钳制")
    ap.add_argument("-p", "--palette", default="mard291", choices=BRANDS, help="色板品牌，默认 mard291")
    ap.add_argument("-m", "--method", default="kmeans", choices=["nearest", "kmeans"],
                    help="量化方法：nearest=直接最近色；kmeans=主色聚类(照片推荐，默认)")
    ap.add_argument("--preset", default="通用", choices=list(PRESETS.keys()),
                    help="照片主题预设：人像/风景/花/动物/插画/人像转插画/通用（按主题自动增强）")
    ap.add_argument("-k", type=int, default=16, help="k-means 主色数，默认 16")
    ap.add_argument("--only", help="仅使用指定色号，逗号分隔，如 A1,B2,F3（不填=全色板）")
    ap.add_argument("-o", "--out", default=None, help="输出前缀（默认=输入文件名）")
    ap.add_argument("-s", "--cell", type=int, default=16, help="预览图每格像素，默认 16")
    ap.add_argument("-L", "--labels", action="store_true", help="在预览图上标注色号")
    ap.add_argument("--clean", action="store_true", help="去孤立杂点（清理量化噪点）")
    ap.add_argument("--outline", action="store_true", default=None,
                    help="卡通描边（沿明暗边界勾轮廓线）；人像转插画默认开启")
    ap.add_argument("--no-outline", action="store_true", help="强制关闭卡通描边")
    ap.add_argument("--outline-threshold", type=int, default=45, help="描边阈值（明暗差 0-150），默认 45")
    ap.add_argument("--cartoon-levels", type=int, default=10, help="卡通色块数（LAB k-means），默认 10")
    ap.add_argument("--suggest-grid", action="store_true",
                    help="扫描候选网格并打印 avgΔE 对比表与推荐 N（不出图）")
    ap.add_argument("--apply-suggest", action="store_true",
                    help="先扫描推荐网格，再用推荐 N 跑完整流程")
    ap.add_argument("--seed", type=int, default=42, help="随机种子，保证可复现")
    ap.add_argument("--delta", choices=["e76", "e2000"], default="e2000",
                    help="色差度量：e2000=CIEDE2000(默认) / e76=ΔE76(A/B)")
    ap.add_argument("--matting", action="store_true", help="开启背景抠图（人像/花/动物推荐）")
    ap.add_argument("--no-matting", action="store_true", help="关闭背景抠图（默认关闭，风景建议关）")
    ap.add_argument("--matting-mode", choices=["auto", "corner", "grabcut", "saliency"], default="auto",
                    help="抠图策略：auto|corner|grabcut|saliency")
    args = ap.parse_args()

    max_grid = min(args.max_grid, MAX_GRID_HARD)
    if args.N > max_grid:
        print(f"⚠ 请求 {args.N}×{args.N} 超过上限 {max_grid}（可用 --max-grid 提高），已按 {max_grid} 处理。", file=sys.stderr)
        args.N = max_grid
    if args.N < 1:
        print("⚠ 网格边长至少 1。", file=sys.stderr)
        sys.exit(1)

    outline = False if args.no_outline else (True if args.outline else None)

    do_matting = bool(args.matting) and not args.no_matting

    if args.suggest_grid or args.apply_suggest:
        rows, recommended, floor = suggest_grid(
            args.image, args.palette, args.method, args.k, args.only, args.seed,
            args.preset, max_grid, cartoon_levels=args.cartoon_levels,
            metric=args.delta, matting=do_matting, matting_mode=args.matting_mode)
        print_suggest_table(rows, recommended, floor, args.preset)
        if args.suggest_grid and not args.apply_suggest:
            return
        args.N = recommended
        print(f"应用推荐网格 N={args.N}", file=sys.stderr)

    out_prefix = args.out or os.path.splitext(args.image)[0]
    out_dir = os.path.dirname(out_prefix)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
        print(f"已创建输出目录: {out_dir}", file=sys.stderr)
    process(args.image, args.N, args.palette, args.method, args.k,
            args.only, out_prefix, args.cell, args.seed, labels=args.labels, preset=args.preset,
            clean=args.clean, outline=outline, outline_threshold=args.outline_threshold,
            cartoon_levels=args.cartoon_levels, metric=args.delta,
            matting=do_matting, matting_mode=args.matting_mode)


if __name__ == "__main__":
    main()
