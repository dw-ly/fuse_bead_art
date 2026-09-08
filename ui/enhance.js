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
  var PRESET_GRID_FLOOR = {
    '人像': 49, '人像转插画': 49, '动物': 39, '插画': 29,
    '通用': 29, '花': 39, '风景': 59
  };
  var DEFAULT_GRID_CANDIDATES = [29, 39, 49, 59, 60];
  var AVG_DE_THRESHOLD = 15;

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

  // 简易 RGB k-means 色块压平（无 OpenCV 时的 LAB 近似）
  function kmeansFlatten(rgba, w, h, nColors, seed) {
    var P = w * h;
    var pixels = new Array(P);
    for (var i = 0; i < P; i++) {
      pixels[i] = [rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2]];
    }
    // mulberry32
    var a = seed | 0;
    function rng() {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    }
    var k = Math.max(2, Math.min(nColors, P));
    var centers = [], chosen = {}, guard = 0;
    while (centers.length < k && guard < 10000) {
      guard++;
      var idx = Math.floor(rng() * P);
      if (!chosen[idx]) { chosen[idx] = true; centers.push(pixels[idx].slice()); }
    }
    var labels = new Int32Array(P);
    for (var iter = 0; iter < 12; iter++) {
      for (var i = 0; i < P; i++) {
        var best = 0, bd = Infinity, p = pixels[i];
        for (var j = 0; j < k; j++) {
          var c = centers[j];
          var d = (p[0] - c[0]) * (p[0] - c[0]) + (p[1] - c[1]) * (p[1] - c[1]) + (p[2] - c[2]) * (p[2] - c[2]);
          if (d < bd) { bd = d; best = j; }
        }
        labels[i] = best;
      }
      var sums = [], cnts = new Int32Array(k);
      for (var j = 0; j < k; j++) sums.push([0, 0, 0]);
      for (var i = 0; i < P; i++) {
        var l = labels[i], p = pixels[i];
        sums[l][0] += p[0]; sums[l][1] += p[1]; sums[l][2] += p[2]; cnts[l]++;
      }
      var moved = 0;
      for (var j = 0; j < k; j++) {
        if (cnts[j] > 0) {
          var nc = [sums[j][0] / cnts[j], sums[j][1] / cnts[j], sums[j][2] / cnts[j]];
          if (Math.abs(nc[0] - centers[j][0]) + Math.abs(nc[1] - centers[j][1]) + Math.abs(nc[2] - centers[j][2]) > 0.5) moved++;
          centers[j] = nc;
        }
      }
      if (moved === 0) break;
    }
    for (var i = 0; i < P; i++) {
      var c = centers[labels[i]];
      rgba[i * 4] = Math.round(c[0]);
      rgba[i * 4 + 1] = Math.round(c[1]);
      rgba[i * 4 + 2] = Math.round(c[2]);
    }
  }

  // 盒式平滑近似双边（多次小半径）
  function multiBoxSmooth(rgba, w, h, passes) {
    passes = passes || 2;
    for (var p = 0; p < passes; p++) {
      var src = new Uint8ClampedArray(rgba);
      for (var y = 1; y < h - 1; y++) for (var x = 1; x < w - 1; x++) {
        var i = (y * w + x) * 4;
        for (var c = 0; c < 3; c++) {
          var sum = 0, wt = 0;
          var center = src[i + c];
          for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
            var j = ((y + dy) * w + (x + dx)) * 4 + c;
            var d = Math.abs(src[j] - center);
            var wgt = d < 40 ? 1 : (d < 80 ? 0.3 : 0.05); // 边缘保持近似
            sum += src[j] * wgt; wt += wgt;
          }
          rgba[i + c] = Math.round(sum / wt);
        }
      }
    }
  }

  function boostSaturation(rgba, factor) {
    for (var i = 0; i < rgba.length; i += 4) {
      var r = rgba[i] / 255, g = rgba[i + 1] / 255, b = rgba[i + 2] / 255;
      var max = Math.max(r, g, b), min = Math.min(r, g, b);
      var l = (max + min) / 2, d = max - min;
      if (d < 1e-6) continue;
      var s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      var ns = Math.min(1, s * factor);
      if (Math.abs(ns - s) < 1e-6) continue;
      // 简易：向均值拉开
      var m = (r + g + b) / 3;
      rgba[i]     = Math.max(0, Math.min(255, Math.round((m + (r - m) * (ns / (s || 1e-6))) * 255)));
      rgba[i + 1] = Math.max(0, Math.min(255, Math.round((m + (g - m) * (ns / (s || 1e-6))) * 255)));
      rgba[i + 2] = Math.max(0, Math.min(255, Math.round((m + (b - m) * (ns / (s || 1e-6))) * 255)));
    }
  }

  // 卡通化：边缘保持平滑 → k-means 色块 → 描边上色（非 AND）→ 提饱和
  // levels: 色块数；outlineStrength: 0 关闭，≥1 涂深色轮廓
  function cartoon(rgba, w, h, levels, outlineStrength) {
    levels = levels || 10;
    if (outlineStrength === undefined) outlineStrength = 1;
    multiBoxSmooth(rgba, w, h, 3);
    kmeansFlatten(rgba, w, h, levels, 42);
    if (outlineStrength > 0) {
      var edge = edgeMap(rgba, w, h);
      var sorted = Array.prototype.slice.call(edge).sort(function (a, b) { return a - b; });
      var thr = sorted[Math.floor(sorted.length * 0.88)] || 30;
      // 轻微膨胀：邻域也标边
      var mark = new Uint8Array(w * h);
      for (var i = 0; i < w * h; i++) if (edge[i] > thr) mark[i] = 1;
      if (outlineStrength >= 1) {
        var dil = new Uint8Array(mark);
        for (var y = 1; y < h - 1; y++) for (var x = 1; x < w - 1; x++) {
          var p = y * w + x;
          if (mark[p]) {
            dil[p - 1] = dil[p + 1] = dil[p - w] = dil[p + w] = 1;
          }
        }
        mark = dil;
      }
      for (var i = 0; i < w * h; i++) {
        if (mark[i]) {
          rgba[i * 4] = 20; rgba[i * 4 + 1] = 18; rgba[i * 4 + 2] = 22;
        }
      }
    }
    boostSaturation(rgba, 1.15);
    return 0;
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
      cartoon(data.data, workingSize, workingSize, 10, 1);
      wctx.putImageData(data, 0, 0);
      steps.push('卡通化（k-means色块+描边上色）');
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
    PRESET_GRID_FLOOR: PRESET_GRID_FLOOR,
    DEFAULT_GRID_CANDIDATES: DEFAULT_GRID_CANDIDATES,
    AVG_DE_THRESHOLD: AVG_DE_THRESHOLD,
    edgeMap: edgeMap,
    saliencyCenter: saliencyCenter,
    boxBlur: boxBlur,
    posterize: posterize,
    unsharp: unsharp,
    cartoon: cartoon,
    kmeansFlatten: kmeansFlatten,
    processImageWithPreset: processImageWithPreset
  };
});
