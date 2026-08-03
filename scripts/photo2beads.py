#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
photo2beads.py — 照片 → 拼豆图纸（M1 原型）

管线：居中裁方 → LANCZOS 缩到 N×N → 量化到豆色（CIELAB ΔE）→ 输出图纸 + 用量清单

依赖：Pillow、numpy（轻量，可离线安装）

用法示例：
    python scripts/photo2beads.py 照片.jpg -N 49                 # 默认: MARD 291 色板, k-means 主色
    python scripts/photo2beads.py 照片.jpg -N 39 -p hama -m nearest
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

# 色号库路径（项目数据资产，由 parse_palette.py 生成）
PALETTE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "bead_palettes.json")
MAX_GRID = 60  # 本项目按 60×60 以内做

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
def quantize_nearest(lab_img, pal_lab):
    """方案A：每个格子直接找 LAB 最近豆色。"""
    flat = lab_img.reshape(-1, 3)
    d = np.sum((flat[:, None, :] - pal_lab[None, :, :]) ** 2, axis=-1)
    return d.argmin(axis=-1).reshape(lab_img.shape[:2])


def quantize_kmeans(lab_img, pal_lab, k, seed):
    """方案B：k-means 主色聚类，再映射每个主色到最近豆色（照片推荐）。"""
    flat = lab_img.reshape(-1, 3).astype(np.float64)
    rng = np.random.default_rng(seed)
    centers = flat[rng.choice(len(flat), k, replace=False)].copy()
    for _ in range(30):
        d = np.sum((flat[:, None, :] - centers[None, :, :]) ** 2, axis=-1)
        labels = d.argmin(axis=-1)
        new_centers = centers.copy()
        for i in range(k):
            m = labels == i
            if m.any():
                new_centers[i] = flat[m].mean(axis=0)
        if np.allclose(new_centers, centers):
            centers = new_centers
            break
        centers = new_centers
    # 每个主色映射到最近豆色
    cd = np.sum((centers[:, None, :] - pal_lab[None, :, :]) ** 2, axis=-1)
    return cd.argmin(axis=-1)[labels].reshape(lab_img.shape[:2])


# ---------------------------------------------------------------- 绘图
def draw_preview(grid, palette, cell, labels=False):
    """圆角豆粒风格预览图，接近成品观感。labels=True 时给每颗豆标注色号。"""
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
            hexc = palette[grid[r, c]][1]
            d.rounded_rectangle([x0, y0, x0 + cell, y0 + cell], radius=radius, fill=hexc)
            if labels:
                code = palette[grid[r, c]][0]
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
            hexc = palette[grid[r, c]][1]
            d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=hexc, outline=(60, 60, 60), width=1)
            # 色号标注 + 自适应文字颜色
            code = palette[grid[r, c]][0]
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
    d.text((ruler, legend_top - 16), f"用量清单（共 {sum(cnt for _, _, cnt in counts)} 颗豆）",
           fill=(30, 30, 30), font=legend_font)
    for i, (code, hexc, cnt) in enumerate(legend_lines):
        y = legend_top + i * lh
        d.rectangle([ruler, y + 3, ruler + 16, y + 17], fill=hexc, outline=(0, 0, 0))
        d.text((ruler + 22, y), f"{code}  {hexc}  ×{cnt}", fill=(30, 30, 30), font=legend_font)
    return img


# ---------------------------------------------------------------- 主流程
def process(image_path, n, brand, method, k, only, out_prefix, cell, seed, labels=False):
    # 1. 读图 + 裁方 + 缩小
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    img = img.resize((n, n), Image.LANCZOS)
    rgb = np.asarray(img)  # (n, n, 3) uint8

    # 2. 色板
    palette = load_palette(brand, only)
    pal_rgb = np.array([list(bytes.fromhex(c[1][1:])) for c in palette], dtype=np.uint8)  # (K,3)
    pal_lab = srgb_to_lab(pal_rgb)
    lab_img = srgb_to_lab(rgb)

    # 3. 量化
    if method == "nearest":
        grid = quantize_nearest(lab_img, pal_lab)
    else:
        k = min(k, min(n * n, len(palette)))
        grid = quantize_kmeans(lab_img, pal_lab, k, seed)

    # 4. 统计与报告
    used = grid.ravel()
    counts = []
    for i in range(len(palette)):
        c = int((used == i).sum())
        if c:
            counts.append((palette[i][0], palette[i][1], c))
    counts.sort(key=lambda x: -x[2])
    avg_de = float(delta_e76(lab_img, pal_lab[grid]).mean())
    unique = len(counts)

    # 5. 输出
    preview_cell = max(cell, 28) if labels else cell
    draw_preview(grid, palette, preview_cell, labels=labels).save(f"{out_prefix}_preview.png")
    draw_spec(grid, palette, counts).save(f"{out_prefix}_spec.png")
    with open(f"{out_prefix}_usage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["color_code", "hex", "count"])
        w.writerows(counts)

    print(f"网格: {n}×{n} = {n * n} 颗豆  |  色板: {brand}（{len(palette)} 色可用，实际用 {unique} 色）")
    print(f"量化方法: {method}{'(k=' + str(k) + ')' if method == 'kmeans' else ''}  |  平均每豆色差 ΔE = {avg_de:.1f}")
    print(f"输出: {out_prefix}_preview.png / _spec.png / _usage.csv")
    if avg_de > 15:
        print(f"[警告] avgΔE={avg_de:.1f} 超过建议阈值 15，人像建议升一档网格（如 39→49）；简单图案可降档省豆。")
    else:
        print(f"[OK] avgΔE={avg_de:.1f} 在建议阈值 15 以内，此分辨率保真度可接受。")
    return grid, counts, avg_de


def main():
    ap = argparse.ArgumentParser(description="照片 → 拼豆图纸（M1 原型）")
    ap.add_argument("image", help="输入照片路径")
    ap.add_argument("-N", type=int, default=49, help=f"网格边长(豆数)，上限 {MAX_GRID}，默认 49")
    ap.add_argument("-p", "--palette", default="mard291", choices=BRANDS, help="色板品牌，默认 mard291")
    ap.add_argument("-m", "--method", default="kmeans", choices=["nearest", "kmeans"],
                    help="量化方法：nearest=直接最近色；kmeans=主色聚类(照片推荐，默认)")
    ap.add_argument("-k", type=int, default=16, help="k-means 主色数，默认 16")
    ap.add_argument("--only", help="仅使用指定色号，逗号分隔，如 A1,B2,F3（不填=全色板）")
    ap.add_argument("-o", "--out", default=None, help="输出前缀（默认=输入文件名）")
    ap.add_argument("-s", "--cell", type=int, default=16, help="预览图每格像素，默认 16")
    ap.add_argument("-L", "--labels", action="store_true", help="在预览图上标注色号")
    ap.add_argument("--seed", type=int, default=42, help="随机种子，保证可复现")
    args = ap.parse_args()

    if args.N > MAX_GRID:
        print(f"⚠ 请求 {args.N}×{args.N} 超过上限 {MAX_GRID}，已按 {MAX_GRID} 处理。", file=sys.stderr)
        args.N = MAX_GRID
    if args.N < 1:
        print("⚠ 网格边长至少 1。", file=sys.stderr)
        sys.exit(1)

    out_prefix = args.out or os.path.splitext(args.image)[0]
    # 自动创建输出目录（后续按"主题/照片名"分文件夹存放）
    out_dir = os.path.dirname(out_prefix)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
        print(f"已创建输出目录: {out_dir}", file=sys.stderr)
    process(args.image, args.N, args.palette, args.method, args.k,
            args.only, out_prefix, args.cell, args.seed, labels=args.labels)


if __name__ == "__main__":
    main()
