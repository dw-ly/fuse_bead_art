/* enhance.js — M3 前端照片增强：按主题预设处理（浏览器 & node 通用算法）
   与 scripts/enhance.py 对齐：主体质心定位、边缘感知背景柔化、饱和度、卡通化。
   浏览器入口：processImageWithPreset(img, preset, N) → N×N ImageData */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BeadsEnhance = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // 预设配置（与 Python 对齐；浏览器端无 OpenCV，人脸精修不做，统一用主体质心）
  var ENHANCE_PRESETS = {
    '通用':       { blur: 0,    sat: 1.00, sharpen: 0,   denoise: 0, cartoon: false, center: false },
    '人像':       { blur: 0.9,  sat: 0.95, sharpen: 0.6, denoise: 0.4, cartoon: false, center: true },
    '风景':       { blur: 0,    sat: 1.10, sharpen: 0,   denoise: 0.4, cartoon: false, center: false },
    '花':         { blur: 1.2,  sat: 1.15, sharpen: 0.8, denoise: 0, cartoon: false, center: true },
    '动物':       { blur: 0.8,  sat: 1.05, sharpen: 0.6, denoise: 0.3, cartoon: false, center: true },
    '插画':       { blur: 0,    sat: 1.05, sharpen: 0.5, denoise: 0, cartoon: false, center: false },
    '人像转插画': { blur: 0,    sat: 1.10, sharpen: 0,   denoise: 0, cartoon: true,  center: true }
  };
  var PRESET_ORDER = ['通用', '人像', '风景', '花', '动物', '插画', '人像转插画'];

  // ---------- 纯像素算法（node 可测） ----------
  function luminanceAt(rgba, i) {
    return 0.299 * rgba[i] + 0.587 * rgba[i + 1] + 0.114 * rgba[i + 2];
  }

  // Sobel 边缘图 → Float32Array(w*h)
  function edgeMap(rgba, w, h) {
    var gray = new Float32Array(w * h);
    for (var i = 0; i < w * h; i++) gray[i] = luminanceAt(rgba, i * 4);
    var edge = new Float32Array(w * h);
    for (var y = 1; y < h - 1; y++) {
      for (var x = 1; x < w - 1; x++) {
        var p = y * w + x;
        var gx = -gray[p - w - 1] - 2 * gray[p - 1] - gray[p + w - 1]
               + gray[p - w + 1] + 2 * gray[p + 1] + gray[p + w + 1];
        var gy = -gray[p - w - 1] - 2 * gray[p - w] - gray[p - w + 1]
               + gray[p + w - 1] + 2 * gray[p + w] + gray[p + w + 1];
        edge[p] = Math.sqrt(gx * gx + gy * gy);
      }
    }
    return edge;
  }

  // 边缘加权质心（主体位置）
  function saliencyCenter(edge, w, h) {
    var sx = 0, sy = 0, sw = 0;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var e = edge[y * w + x];
      sx += x * e; sy += y * e; sw += e;
    }
    if (sw === 0) return { x: w / 2, y: h / 2 };
    return { x: sx / sw, y: sy / sw };
  }

  // 盒式模糊（遮罩平滑用）
  function boxBlur(src, w, h, radius) {
    var r = Math.max(1, Math.floor(radius));
    var n = 2 * r + 1;
    var tmp = new Float32Array(w * h);
    var out = new Float32Array(w * h);
    var x, y, i, add, sub;
    for (y = 0; y < h; y++) {
      var sum = 0;
      for (x = -r; x <= r; x++) sum += src[y * w + Math.min(Math.max(x, 0), w - 1)];
      for (x = 0; x < w; x++) {
        tmp[y * w + x] = sum / n;
        add = src[y * w + Math.min(Math.max(x + r + 1, 0), w - 1)];
        sub = src[y * w + Math.min(Math.max(x - r, 0), w - 1)];
        sum += add - sub;
      }
    }
    for (x = 0; x < w; x++) {
      var sum2 = 0;
      for (y = -r; y <= r; y++) sum2 += tmp[Math.min(Math.max(y, 0), h - 1) * w + x];
      for (y = 0; y < h; y++) {
        out[y * w + x] = sum2 / n;
        add = tmp[Math.min(Math.max(y + r + 1, 0), h - 1) * w + x];
        sub = tmp[Math.min(Math.max(y - r, 0), h - 1) * w + x];
        sum2 += add - sub;
      }
    }
    return out;
  }

  // 颜色分级（卡通用）
  function posterize(rgba, levels) {
    var q = Math.max(1, Math.floor(256 / levels));
    var half = Math.floor(q / 2);
    for (var i = 0; i < rgba.length; i += 4) {
      rgba[i]     = Math.min(255, Math.floor(rgba[i] / q) * q + half);
      rgba[i + 1] = Math.min(255, Math.floor(rgba[i + 1] / q) * q + half);
      rgba[i + 2] = Math.min(255, Math.floor(rgba[i + 2] / q) * q + half);
    }
  }

  // 非锐化掩蔽（对 ImageData.data 就地操作）
  function unsharp(rgba, w, h, amount) {
    // 简化为局部均值近似（3x3 邻域）做差
    var src = new Float32Array(rgba.length);
    for (var i = 0; i < rgba.length; i++) src[i] = rgba[i];
    for (var y = 1; y < h - 1; y++) for (var x = 1; x < w - 1; x++) {
      var p = y * w + x, q = p * 4;
      for (var c = 0; c < 3; c++) {
        var m = (src[(p - w - 1) * 4 + c] + src[(p - w) * 4 + c] + src[(p - w + 1) * 4 + c]
               + src[(p - 1) * 4 + c] + src[p * 4 + c] + src[(p + 1) * 4 + c]
               + src[(p + w - 1) * 4 + c] + src[(p + w) * 4 + c] + src[(p + w + 1) * 4 + c]) / 9;
        rgba[q + c] = Math.max(0, Math.min(255, src[q + c] + amount * (src[q + c] - m)));
      }
    }
  }

  // 卡通化：分级 + 勾边（就地操作，返回用到的阈值）
  function cartoon(rgba, w, h) {
    var edge = edgeMap(rgba, w, h);
    // 自适应阈值：取边缘的第 92 百分位
    var sorted = Array.prototype.slice.call(edge).sort(function (a, b) { return a - b; });
    var thr = sorted[Math.floor(sorted.length * 0.92)] || 30;
    posterize(rgba, 5);
    for (var i = 0; i < w * h; i++) {
      if (edge[i] > thr) { rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = 0; }
    }
    return thr;
  }

  // ---------- 浏览器编排（依赖 canvas） ----------
  // img: HTMLImageElement; preset: 预设名; N: 网格边长
  // 返回 { imageData, steps:[...] }，imageData 为 N×N RGBA
  function processImageWithPreset(img, preset, N, workingSize) {
    var cfg = ENHANCE_PRESETS[preset] || ENHANCE_PRESETS['通用'];
    var steps = [];
    workingSize = workingSize || 512;

    // 1. 主体质心（在缩小图上算，再映射回原图坐标）
    var ow = img.naturalWidth, oh = img.naturalHeight;
    var cx = ow / 2, cy = oh / 2;
    if (cfg.center) {
      var anal = document.createElement('canvas');
      var scale = Math.min(1, 400 / Math.max(ow, oh));
      anal.width = Math.max(1, Math.round(ow * scale));
      anal.height = Math.max(1, Math.round(oh * scale));
      var actx = anal.getContext('2d');
      actx.imageSmoothingEnabled = true;
      actx.drawImage(img, 0, 0, anal.width, anal.height);
      var adata = actx.getImageData(0, 0, anal.width, anal.height);
      var center = saliencyCenter(edgeMap(adata.data, anal.width, anal.height), anal.width, anal.height);
      cx = center.x / scale; cy = center.y / scale;
      steps.push('主体质心定位');
    }

    // 2. 裁方（质心居中或纯中心）
    var side = Math.min(ow, oh);
    var left = Math.max(0, Math.min(cx - side / 2, ow - side));
    var top = Math.max(0, Math.min(cy - side / 2, oh - side));

    // 3. 画到工作画布
    var work = document.createElement('canvas');
    work.width = work.height = workingSize;
    var wctx = work.getContext('2d');
    wctx.imageSmoothingEnabled = true;
    wctx.imageSmoothingQuality = 'high';
    wctx.drawImage(img, left, top, side, side, 0, 0, workingSize, workingSize);

    // 4. 增强
    var data = wctx.getImageData(0, 0, workingSize, workingSize);

    if (cfg.cartoon) {
      cartoon(data.data, workingSize, workingSize);
      steps.push('卡通化');
    } else {
      if (cfg.blur > 0) {
        // 边缘遮罩 → 模糊层带 alpha 叠加
        var edge = edgeMap(data.data, workingSize, workingSize);
        var mask = boxBlur(edge, workingSize, workingSize, Math.max(2, cfg.blur * 5));
        var mn = mask[0], mx = mask[0];
        for (var i = 0; i < mask.length; i++) {
          if (mask[i] < mn) mn = mask[i];
          if (mask[i] > mx) mx = mask[i];
        }
        var range = (mx - mn) || 1;
        for (var i = 0; i < mask.length; i++) mask[i] = (mask[i] - mn) / range;

        var blurC = document.createElement('canvas');
        blurC.width = blurC.height = workingSize;
        var bctx = blurC.getContext('2d');
        bctx.filter = 'blur(' + Math.max(2, cfg.blur * workingSize * 0.027) + 'px)';
        bctx.drawImage(work, 0, 0);
        var bdata = bctx.getImageData(0, 0, workingSize, workingSize);
        for (var i = 0; i < workingSize * workingSize; i++) {
          bdata.data[i * 4 + 3] = Math.round(255 * (1 - mask[i]));  // 背景权重作 alpha
        }
        bctx.putImageData(bdata, 0, 0);
        // 合成：清晰底 + 模糊层
        var outC = document.createElement('canvas');
        outC.width = outC.height = workingSize;
        var octx = outC.getContext('2d');
        octx.drawImage(work, 0, 0);
        octx.drawImage(blurC, 0, 0);
        work = outC;
        steps.push('背景柔化×' + cfg.blur);
      }

      if (cfg.sat !== 1) {
        var satC = document.createElement('canvas');
        satC.width = satC.height = workingSize;
        var sctx = satC.getContext('2d');
        sctx.filter = 'saturate(' + cfg.sat + ')';
        sctx.drawImage(work, 0, 0);
        work = satC;
        steps.push('饱和度×' + cfg.sat);
      }

      if (cfg.sharpen > 0) {
        var sdata = work.getContext('2d').getImageData(0, 0, workingSize, workingSize);
        unsharp(sdata.data, workingSize, workingSize, cfg.sharpen * 0.7);
        work.getContext('2d').putImageData(sdata, 0, 0);
        steps.push('锐化×' + cfg.sharpen);
      }
    }

    // 5. 缩到 N×N
    var small = document.createElement('canvas');
    small.width = small.height = N;
    var sctx = small.getContext('2d');
    sctx.imageSmoothingEnabled = true;
    sctx.imageSmoothingQuality = 'high';
    sctx.drawImage(work, 0, 0, N, N);

    return { imageData: sctx.getImageData(0, 0, N, N), steps: steps };
  }

  return {
    ENHANCE_PRESETS: ENHANCE_PRESETS,
    PRESET_ORDER: PRESET_ORDER,
    edgeMap: edgeMap,
    saliencyCenter: saliencyCenter,
    boxBlur: boxBlur,
    posterize: posterize,
    unsharp: unsharp,
    cartoon: cartoon,
    processImageWithPreset: processImageWithPreset
  };
});
