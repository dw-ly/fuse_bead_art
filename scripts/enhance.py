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
# face=是否做人脸检测居中裁剪 cartoon=是否卡通化
PRESETS = {
    '通用':       dict(blur=0.0, sat=1.00, sharpen=0.0, denoise=0.0, cartoon=False, face=False),
    '人像':       dict(blur=0.9, sat=0.95, sharpen=0.6, denoise=0.4, cartoon=False, face=True),
    '风景':       dict(blur=0.0, sat=1.10, sharpen=0.0, denoise=0.4, cartoon=False, face=False),
    '花':         dict(blur=1.2, sat=1.15, sharpen=0.8, denoise=0.0, cartoon=False, face=False),
    '动物':       dict(blur=0.8, sat=1.05, sharpen=0.6, denoise=0.3, cartoon=False, face=False),
    '插画':       dict(blur=0.0, sat=1.05, sharpen=0.5, denoise=0.0, cartoon=False, face=False),
    '人像转插画': dict(blur=0.0, sat=1.10, sharpen=0.0, denoise=0.0, cartoon=True,  face=True),
}
PRESET_ORDER = ['通用', '人像', '风景', '花', '动物', '插画', '人像转插画']


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
        # scaleFactor=1.05：尺度步长更细，避免漏检（1.1 会跳过部分人脸尺度）
        faces = cascade.detectMultiScale(gray, 1.05, 3, minSize=(min_size, min_size))
        good = [(x, y, w, h) for (x, y, w, h) in faces if _is_skin_like(arr[y:y + h, x:x + w])]
        if not good:
            return None
        x, y, w, h = max(good, key=lambda f: f[2] * f[3])
        return (x + w / 2, y + h / 2, max(w, h))
    except Exception:
        return None


def crop_square(img, face=None):
    """裁成方形。有脸则围绕人脸裁剪，否则居中裁方。
    脸在成品中占比自适应：特写 0.6（紧）→ 远景小脸 0.3（放宽，包含身体），避免过度放大。"""
    w, h = img.size
    if face:
        fx, fy, fs = face
        min_dim = min(w, h)
        f = fs / min_dim
        if f >= 0.2:
            ratio = 0.6
        elif f <= 0.05:
            ratio = 0.3
        else:
            ratio = 0.3 + (f - 0.05) / 0.15 * 0.3
        side = int(fs / ratio)
        side = min(max(side, 80), min_dim)   # 至少 80px，且不超出图幅
        left = int(max(0, min(fx - side / 2, w - side)))
        top = int(max(0, min(fy - side / 2, h - side)))
        return img.crop((left, top, left + side, top + side)), True
    side = min(w, h)
    return img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2)), False


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
    # S 通道在 uint8 [0,255] 域乘系数（float 运算后截回）
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


def cartoon(img, levels=5):
    """卡通化（人像转插画）：双边压平 → 颜色分级 → 勾深色轮廓线。"""
    arr = np.asarray(img)
    # 1. 强双边压平：皮肤/纹理变平涂
    flat = cv2.bilateralFilter(arr, 9, 60, 60)
    flat = cv2.bilateralFilter(flat, 9, 60, 60)
    # 2. 颜色分级：每个通道压缩成 levels 级 → 动漫平涂色块（用 int32 防 uint8 溢出）
    q = max(1, 256 // levels)
    flat = ((flat.astype(np.int32) // q) * q + q // 2)
    flat = np.clip(flat, 0, 255).astype(np.uint8)
    # 3. 勾边：自适应阈值提取轮廓，压成黑色线条
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    gray_blur = cv2.medianBlur(gray, 5)
    edges = cv2.adaptiveThreshold(gray_blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                  cv2.THRESH_BINARY, 9, 10)
    outline = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)
    result = cv2.bitwise_and(flat, outline)
    return Image.fromarray(result)


# ---------------------------------------------------------------- 主入口
def apply_preset(img, preset, log=None):
    """按预设处理图片，返回处理后的方形图（已裁剪+增强）。"""
    if preset not in PRESETS:
        preset = '通用'
    cfg = PRESETS[preset]
    if log is None:
        log = lambda *_: None

    if preset == '通用' or not _HAS_CV2:
        if preset != '通用' and not _HAS_CV2:
            log('[警告] 未安装 OpenCV，预设增强不可用，已回退到通用处理', True)
        return crop_square(img)[0]

    face = detect_face(img) if cfg['face'] else None
    if cfg['face']:
        log(f'人脸检测：{"检测到，按脸居中裁剪" if face else "未检测到，用中心裁剪"}')
    img, _ = crop_square(img, face)

    if cfg['cartoon']:
        log(f'卡通化处理（{preset}）')
        return cartoon(img)

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
