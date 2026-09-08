#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enhance.py — M3 照片增强：按主题预设处理照片

预设处理在量化前对原图执行：人脸居中裁剪、边缘感知背景柔化、
饱和度/锐化/降噪调整、卡通化（人像转插画）。

依赖：numpy、Pillow、opencv-python-headless（<5，4.x 才带 CascadeClassifier）
OpenCV 缺失时自动回退到"通用"（仅居中裁方）。
"""
import os

import numpy as np
from PIL import Image

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    _HAS_CV2 = False

# ---------------------------------------------------------------- 预设定义
# blur=边缘感知背景柔化强度(0关闭) sat=饱和度倍率 sharpen=锐化强度 denoise=降噪强度
# face=是否做人脸检测 center=是否按主体质心居中(风景/插画/通用不居中) cartoon=是否卡通化
PRESETS = {
    '通用':       dict(blur=0.0, sat=1.00, sharpen=0.0, denoise=0.0, cartoon=False, face=False, center=False),
    '人像':       dict(blur=0.9, sat=0.95, sharpen=0.6, denoise=0.4, cartoon=False, face=True,  center=True),
    '风景':       dict(blur=0.0, sat=1.10, sharpen=0.0, denoise=0.4, cartoon=False, face=False, center=False),
    '花':         dict(blur=1.2, sat=1.15, sharpen=0.8, denoise=0.0, cartoon=False, face=False, center=True),
    '动物':       dict(blur=0.8, sat=1.05, sharpen=0.6, denoise=0.3, cartoon=False, face=False, center=True),
    '插画':       dict(blur=0.0, sat=1.05, sharpen=0.5, denoise=0.0, cartoon=False, face=False, center=False),
    '人像转插画': dict(blur=0.0, sat=1.10, sharpen=0.0, denoise=0.0, cartoon=True,  face=True,  center=True),
}
PRESET_ORDER = ['通用', '人像', '风景', '花', '动物', '插画', '人像转插画']

# 主体类型 → 最小网格下限（docs §4.1）
PRESET_GRID_FLOOR = {
    '人像': 49,
    '人像转插画': 49,
    '动物': 39,
    '插画': 29,
    '通用': 29,
    '花': 39,
    '风景': 59,
}


def _cascade_path():
    """人脸级联路径：优先项目内 data/models，其次 OpenCV 自带。"""
    local = os.path.join(os.path.dirname(__file__), '..', 'data', 'models',
                         'haarcascade_frontalface_default.xml')
    if os.path.exists(local):
        return local
    if _HAS_CV2:
        p = os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------- 检测
def _is_skin_like(box):
    """肤色校验：过滤 Haar 误检。RGB 平均满足 R>G>B 且偏暖色。"""
    r = box[..., 0].astype(np.float32).mean()
    g = box[..., 1].astype(np.float32).mean()
    b = box[..., 2].astype(np.float32).mean()
    return r > g > b and (r - b) > 15 and 60 < r < 255


def detect_face(img):
    """检测人脸，返回 (cx, cy, size) 或 None。参数放宽 + 肤色校验过滤误检。"""
    if not _HAS_CV2:
        return None
    p = _cascade_path()
    if not p:
        return None
    try:
        cascade = cv2.CascadeClassifier(p)
        arr = np.asarray(img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        min_size = max(40, min(img.size) // 100)
        faces = cascade.detectMultiScale(gray, 1.05, 3, minSize=(min_size, min_size))
        good = [(x, y, w, h) for (x, y, w, h) in faces if _is_skin_like(arr[y:y + h, x:x + w])]
        if not good:
            return None
        x, y, w, h = max(good, key=lambda f: f[2] * f[3])
        return (x + w / 2, y + h / 2, max(w, h))
    except Exception:
        return None


def _edge_centroid(img):
    """边缘加权质心：主体位置（边缘密集处），对口罩/角度免疫。
    在缩小到 400px 内计算（加速 + 抑制噪点），再映射回原坐标。"""
    if not _HAS_CV2:
        return (img.width / 2, img.height / 2)
    small = np.asarray(img.resize((min(img.width, 400), min(img.height, 400)), Image.LANCZOS))
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    edge = cv2.magnitude(gx, gy)
    h, w = edge.shape
    ys, xs = np.mgrid[0:h, 0:w]
    wsum = float(edge.sum()) + 1e-6
    cx = float((xs * edge).sum()) / wsum
    cy = float((ys * edge).sum()) / wsum
    return (cx * img.width / w, cy * img.height / h)


def crop_square(img, face=None, center_on_subject=True):
    """裁成方形。

    - 有可靠人脸（脸/短边≥0.08 且与主体质心一致）→ 按脸裁剪（自适应比例）
    - 否则 center_on_subject=True → 以边缘质心（主体位置）为中心裁方，主体居中更稳
    - 否则 → 纯居中裁方
    """
    w, h = img.size
    min_dim = min(w, h)

    if face is not None and face[2] / min_dim >= 0.08:
        fx, fy, fs = face
        cx, cy = _edge_centroid(img)
        if abs(fx - cx) <= 0.15 * min_dim and abs(fy - cy) <= 0.25 * min_dim:
            f = fs / min_dim
            if f >= 0.2:
                ratio = 0.6
            elif f <= 0.05:
                ratio = 0.3
            else:
                ratio = 0.3 + (f - 0.05) / 0.15 * 0.3
            side = int(fs / ratio)
            side = min(max(side, 80), min_dim)
            left = int(max(0, min(fx - side / 2, w - side)))
            top = int(max(0, min(fy - side / 2, h - side)))
            return img.crop((left, top, left + side, top + side)), True

    cx, cy = _edge_centroid(img) if center_on_subject else (w / 2, h / 2)
    side = min_dim
    left = int(max(0, min(cx - side / 2, w - side)))
    top = int(max(0, min(cy - side / 2, h - side)))
    return img.crop((left, top, left + side, top + side)), False


# ---------------------------------------------------------------- 增强操作
def edge_blur(img, strength):
    """边缘感知背景柔化：边缘密集区(主体)保持锐利，平滑区(背景)压成大片纯色。"""
    if strength <= 0:
        return img
    arr = np.asarray(img).astype(np.float32)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edges = cv2.magnitude(gx, gy)
    smooth = cv2.GaussianBlur(edges, (0, 0), sigmaX=30 * strength + 8)
    mmin, mmax = float(smooth.min()), float(smooth.max())
    mask = (smooth - mmin) / (mmax - mmin + 1e-6)
    blurred = cv2.GaussianBlur(arr, (0, 0), sigmaX=20 * strength + 8)
    out = arr * mask[..., None] + blurred * (1 - mask)[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def adjust_saturation(img, factor):
    if abs(factor - 1.0) < 1e-6:
        return img
    arr = np.asarray(img).astype(np.uint8)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    s = np.clip(hsv[..., 1].astype(np.float32) * factor, 0, 255).astype(np.uint8)
    hsv[..., 1] = s
    return Image.fromarray(cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB))


def denoise(img, strength):
    if strength <= 0:
        return img
    arr = np.asarray(img)
    d = int(5 + strength * 15)
    if d % 2 == 0:
        d += 1
    out = cv2.bilateralFilter(arr, d, 75 * strength + 25, 75 * strength + 25)
    return Image.fromarray(out)


def sharpen(img, amount):
    if amount <= 0:
        return img
    arr = np.asarray(img).astype(np.float32)
    blur = cv2.GaussianBlur(arr, (0, 0), sigmaX=3)
    out = arr + amount * (arr - blur)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def _lab_kmeans_flatten(arr, n_colors, seed=42):
    """在 LAB 空间 k-means 压成 n_colors 色块，返回 RGB uint8。"""
    h, w = arr.shape[:2]
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2LAB).astype(np.float32)
    flat = lab.reshape(-1, 3)
    # 子采样加速（最多 8k 点）
    rng = np.random.default_rng(seed)
    n = flat.shape[0]
    sample_n = min(n, 8000)
    sample = flat[rng.choice(n, sample_n, replace=False)]
    # 简易 k-means
    k = max(2, min(n_colors, sample_n))
    centers = sample[rng.choice(sample_n, k, replace=False)].copy()
    for _ in range(20):
        d = np.sum((sample[:, None, :] - centers[None, :, :]) ** 2, axis=-1)
        labels = d.argmin(axis=-1)
        new_c = centers.copy()
        for i in range(k):
            m = labels == i
            if m.any():
                new_c[i] = sample[m].mean(axis=0)
        if np.allclose(new_c, centers, atol=0.5):
            centers = new_c
            break
        centers = new_c
    d_all = np.sum((flat[:, None, :] - centers[None, :, :]) ** 2, axis=-1)
    assigned = centers[d_all.argmin(axis=-1)].reshape(h, w, 3)
    out_lab = np.clip(assigned, 0, 255).astype(np.uint8)
    return cv2.cvtColor(out_lab, cv2.COLOR_LAB2RGB)


def cartoon(img, levels=10, outline_strength=1.0):
    """卡通化（人像转插画）：边缘保持压平 → LAB k-means 色块 → 描边上色 → 提饱和。

    与旧版差异：不用 per-channel posterize；不用 bitwise_and（会挖空），
    改为在扁平图上把边缘像素涂成深色轮廓。

    levels: 色块数（约 8–12）
    outline_strength: 0 关闭描边；1 默认；越大膨胀越多 / 线越粗
    """
    arr = np.asarray(img).astype(np.uint8)
    # 1. 边缘保持压平
    if hasattr(cv2, 'edgePreservingFilter'):
        flat = cv2.edgePreservingFilter(arr, flags=1, sigma_s=60, sigma_r=0.4)
        if hasattr(cv2, 'stylization') and outline_strength > 0:
            # 轻 stylization 再混回，避免过度油画感
            sty = cv2.stylization(flat, sigma_s=40, sigma_r=0.3)
            flat = cv2.addWeighted(flat, 0.7, sty, 0.3, 0)
    else:
        flat = arr
        for _ in range(3):
            flat = cv2.bilateralFilter(flat, 9, 75, 75)

    # 2. LAB / RGB k-means 色块（非通道 posterize）
    flat = _lab_kmeans_flatten(flat, n_colors=levels)

    # 3. 轮廓：在扁平灰图上检测，轻微膨胀，涂深色（不 bitwise_and）
    if outline_strength > 0:
        gray = cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 40, 120)
        if edges.sum() < gray.size * 0.005:
            # Canny 太稀时回退自适应阈值
            blur = cv2.medianBlur(gray, 5)
            edges = 255 - cv2.adaptiveThreshold(
                blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 8)
        k = max(1, int(round(outline_strength)))
        if k > 0:
            kernel = np.ones((k, k), np.uint8)
            edges = cv2.dilate(edges, kernel, iterations=1)
        # 深色轮廓（近黑，略留一点色以免死黑死板）
        dark = np.array([20, 18, 22], dtype=np.uint8)
        mask = edges > 0
        flat = flat.copy()
        flat[mask] = dark

    # 4. 轻微提饱和（拼豆成品更鲜）
    out = Image.fromarray(flat)
    out = adjust_saturation(out, 1.15)
    return out


# ---------------------------------------------------------------- 主入口
def apply_preset(img, preset, log=None, cartoon_levels=10, cartoon_outline=1.0):
    """按预设处理图片，返回处理后的方形图（已裁剪+增强）。"""
    if preset not in PRESETS:
        preset = '通用'
    cfg = PRESETS[preset]
    if log is None:
        log = lambda *_: None

    if preset == '通用' or not _HAS_CV2:
        if preset != '通用' and not _HAS_CV2:
            log('[警告] 未安装 OpenCV，预设增强不可用，已回退到通用处理', True)
        return crop_square(img, center_on_subject=False)[0]

    face = detect_face(img) if cfg['face'] else None
    img, used_face = crop_square(img, face, center_on_subject=cfg['center'])
    if cfg['face']:
        if used_face:
            log('人脸检测：检测到可靠人脸，按脸居中裁剪')
        else:
            log('人脸检测：未采用人脸（不存在或置信度不足/与主体不一致），按主体质心定位')

    if cfg['cartoon']:
        log(f'卡通化处理（{preset}，levels={cartoon_levels}）')
        return cartoon(img, levels=cartoon_levels, outline_strength=cartoon_outline)

    steps = []
    if cfg['blur'] > 0:
        img = edge_blur(img, cfg['blur'])
        steps.append(f'背景柔化×{cfg["blur"]}')
    if abs(cfg['sat'] - 1.0) > 1e-6:
        img = adjust_saturation(img, cfg['sat'])
        steps.append(f'饱和度×{cfg["sat"]}')
    if cfg['denoise'] > 0:
        img = denoise(img, cfg['denoise'])
        steps.append(f'降噪×{cfg["denoise"]}')
    if cfg['sharpen'] > 0:
        img = sharpen(img, cfg['sharpen'])
        steps.append(f'锐化×{cfg["sharpen"]}')
    log(f'增强：{preset} → ' + ('、'.join(steps) if steps else '无'))
    return img
