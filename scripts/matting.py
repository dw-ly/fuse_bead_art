#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""matting.py — 本地背景抠图（无强制 GPU）

策略（auto）：
1. corner_flood — 四角近乎同色 → 从边界洪水填充/色度距离遮罩
2. grabcut_face — OpenCV + 人脸 → GrabCut（脸框外扩 + 外圈 probable BG）
3. saliency_soft — 边缘/显著性中心；远离主体且低边缘 → BG

输出 RGBA（BG alpha=0）或 RGB（BG 替换为近白/用户色）。
"""
from __future__ import annotations

import numpy as np
from PIL import Image

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    _HAS_CV2 = False

try:
    from enhance import detect_face, _cascade_path
except ImportError:
    detect_face = None
    _cascade_path = None


def _corners_similar(rgb, max_std=18.0, max_pair=22.0):
    """四角小块是否近似同一平坦色。"""
    h, w = rgb.shape[:2]
    s = max(4, min(h, w) // 16)
    patches = [
        rgb[:s, :s],
        rgb[:s, -s:],
        rgb[-s:, :s],
        rgb[-s:, -s:],
    ]
    means = np.array([p.reshape(-1, 3).mean(axis=0) for p in patches], dtype=np.float64)
    stds = np.array([p.reshape(-1, 3).std(axis=0).mean() for p in patches])
    if float(stds.max()) > max_std:
        return False, means.mean(axis=0)
    # pairwise mean distance
    d = np.sqrt(((means[:, None, :] - means[None, :, :]) ** 2).sum(axis=-1))
    if float(d.max()) > max_pair:
        return False, means.mean(axis=0)
    return True, means.mean(axis=0)


def corner_flood(rgb, thr=28.0):
    """从四边向内按 RGB 距离洪水，标为背景。返回 float mask 1=前景。"""
    h, w = rgb.shape[:2]
    ok, bg = _corners_similar(rgb)
    if not ok:
        return None
    bg = bg.astype(np.float64)
    arr = rgb.astype(np.float64)
    dist = np.sqrt(((arr - bg) ** 2).sum(axis=-1))
    # seed from border pixels close to bg
    visited = np.zeros((h, w), dtype=bool)
    from collections import deque
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if dist[y, x] <= thr:
                q.append((y, x))
                visited[y, x] = True
    for y in range(h):
        for x in (0, w - 1):
            if not visited[y, x] and dist[y, x] <= thr:
                q.append((y, x))
                visited[y, x] = True
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                if dist[ny, nx] <= thr * 1.15:
                    visited[ny, nx] = True
                    q.append((ny, nx))
    fg = (~visited).astype(np.float32)
    # if almost everything is BG, fail
    if fg.mean() < 0.02 or fg.mean() > 0.98:
        return None
    return fg


def grabcut_face(rgb, iterations=4):
    """人脸检测初始化 GrabCut。返回 float mask 或 None。"""
    if not _HAS_CV2 or detect_face is None:
        return None
    img = Image.fromarray(rgb)
    face = detect_face(img)
    if face is None:
        return None
    h, w = rgb.shape[:2]
    cx, cy, size = face
    # expand face rect to cover head/shoulders-ish
    half = size * 1.35
    x0 = int(max(0, cx - half))
    y0 = int(max(0, cy - half * 1.2))
    x1 = int(min(w, cx + half))
    y1 = int(min(h, cy + half * 1.5))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    mask = np.full((h, w), cv2.GC_BGD, dtype=np.uint8)
    # probable BG outside expanded rect
    pad = int(max(8, min(h, w) * 0.04))
    mask[pad:h - pad, pad:w - pad] = cv2.GC_PR_BGD
    mask[y0:y1, x0:x1] = cv2.GC_PR_FGD
    # sure FG in inner face
    ix0 = int(cx - size * 0.35)
    iy0 = int(cy - size * 0.35)
    ix1 = int(cx + size * 0.35)
    iy1 = int(cy + size * 0.35)
    ix0, iy0 = max(0, ix0), max(0, iy0)
    ix1, iy1 = min(w, ix1), min(h, iy1)
    mask[iy0:iy1, ix0:ix1] = cv2.GC_FGD
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    try:
        cv2.grabCut(bgr, mask, None, bgd, fgd, iterations, cv2.GC_INIT_WITH_MASK)
    except Exception:
        return None
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1.0, 0.0).astype(np.float32)
    if fg.mean() < 0.02 or fg.mean() > 0.95:
        return None
    return fg


def saliency_soft(rgb):
    """边缘显著性中心：远离中心且低边缘 → BG。返回 soft mask。"""
    h, w = rgb.shape[:2]
    gray = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.float64)
    # sobel-ish
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
    gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    edge = np.sqrt(gx * gx + gy * gy)
    # saliency center
    e = edge + 1e-6
    ys, xs = np.mgrid[0:h, 0:w]
    cx = float((xs * e).sum() / e.sum())
    cy = float((ys * e).sum() / e.sum())
    dist = np.sqrt(((xs - cx) / max(w, 1)) ** 2 + ((ys - cy) / max(h, 1)) ** 2)
    e_n = edge / (edge.max() + 1e-6)
    # high edge or near center → FG
    score = 0.55 * (1.0 - np.clip(dist / 0.55, 0, 1)) + 0.45 * e_n
    # also boost if color differs from border mean
    border = np.concatenate([
        rgb[0, :].reshape(-1, 3), rgb[-1, :].reshape(-1, 3),
        rgb[:, 0].reshape(-1, 3), rgb[:, -1].reshape(-1, 3)
    ], axis=0).astype(np.float64)
    bg = border.mean(axis=0)
    cdist = np.sqrt(((rgb.astype(np.float64) - bg) ** 2).sum(axis=-1))
    cdist = cdist / (cdist.max() + 1e-6)
    score = 0.5 * score + 0.5 * cdist
    fg = (score > 0.35).astype(np.float32)
    # light morph: keep largest component-ish via distance from center
    if fg.mean() < 0.05:
        fg = (dist < 0.35).astype(np.float32)
    return fg


def auto_matte(rgb):
    """自动选策略，返回 (mask, mode_name)。"""
    m = corner_flood(rgb)
    if m is not None:
        return m, "corner_flood"
    m = grabcut_face(rgb)
    if m is not None:
        return m, "grabcut_face"
    return saliency_soft(rgb), "saliency_soft"


def apply_matting(img, mode="auto", bg_color=None, as_rgba=True):
    """对 PIL Image 抠图。

    mode: auto|corner|grabcut|saliency
    bg_color: None → 透明；否则 RGB tuple 替换背景
    as_rgba: True 返回 RGBA；False 且 bg_color 时返回 RGB
    返回 (PIL.Image, mode_used)
    """
    rgb = np.asarray(img.convert("RGB"))
    if mode == "auto":
        mask, used = auto_matte(rgb)
    elif mode == "corner":
        mask = corner_flood(rgb)
        used = "corner_flood"
        if mask is None:
            mask, used = saliency_soft(rgb), "saliency_soft(fallback)"
    elif mode == "grabcut":
        mask = grabcut_face(rgb)
        used = "grabcut_face"
        if mask is None:
            mask, used = auto_matte(rgb)
            used = used + "(fallback)"
    else:
        mask, used = saliency_soft(rgb), "saliency_soft"

    alpha = (np.clip(mask, 0, 1) * 255).astype(np.uint8)
    if bg_color is not None:
        out = rgb.copy()
        bg = np.array(bg_color, dtype=np.uint8)
        out[alpha < 128] = bg
        if as_rgba:
            a = np.where(alpha < 128, 0, 255).astype(np.uint8)
            rgba = np.dstack([out, a])
            return Image.fromarray(rgba, "RGBA"), used
        return Image.fromarray(out, "RGB"), used

    rgba = np.dstack([rgb, alpha])
    return Image.fromarray(rgba, "RGBA"), used
