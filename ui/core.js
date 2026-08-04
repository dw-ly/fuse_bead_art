/* core.js — 拼豆转换核心算法（浏览器 & node 通用，无 DOM 依赖）
   算法与 scripts/photo2beads.py 一致：CIELAB + ΔE76 最近色量化。
   浏览器: <script src="core.js"> → window.BeadsCore
   node:   require('./core.js') */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BeadsCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ---------- 颜色数学 ----------
  function srgbToLab(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    var lin = function (c) {
      return c > 0.04045 ? Math.pow((c + 0.055) / 1.055, 2.4) : c / 12.92;
    };
    r = lin(r); g = lin(g); b = lin(b);
    var x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b;
    var y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b;
    var z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b;
    var Xn = 0.95047, Yn = 1.0, Zn = 1.08883;
    var eps = 216 / 24389, kap = 24389 / 27;
    var f = function (t) { return t > eps ? Math.cbrt(t) : (kap * t + 16) / 116; };
    var fx = f(x / Xn), fy = f(y / Yn), fz = f(z / Zn);
    return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
  }

  // ---------- 可复现随机（mulberry32） ----------
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  // ---------- 色板 ----------
  function flattenPalette(data, brand, only) {
    var series = data[brand], colors = [];
    Object.keys(series).forEach(function (key) {
      series[key].colors.forEach(function (c) { colors.push([c[0], c[1]]); });
    });
    if (only) {
      var wanted = {};
      only.split(',').forEach(function (s) {
        s = s.trim().toUpperCase();
        if (s) wanted[s] = true;
      });
      var filtered = colors.filter(function (c) { return wanted[c[0].toUpperCase()]; });
      if (filtered.length) return filtered;
    }
    return colors;
  }

  function paletteLabs(colors) {
    return colors.map(function (c) {
      return srgbToLab(parseInt(c[1].slice(1, 3), 16),
                       parseInt(c[1].slice(3, 5), 16),
                       parseInt(c[1].slice(5, 7), 16));
    });
  }

  // ---------- 量化 ----------
  function quantizeNearest(pixels, palLabs) {
    var P = pixels.length, K = palLabs.length;
    var grid = new Int32Array(P);
    for (var i = 0; i < P; i++) {
      var best = 0, bd = Infinity, p = pixels[i];
      for (var j = 0; j < K; j++) {
        var c = palLabs[j];
        var d = (p[0] - c[0]) * (p[0] - c[0]) + (p[1] - c[1]) * (p[1] - c[1]) + (p[2] - c[2]) * (p[2] - c[2]);
        if (d < bd) { bd = d; best = j; }
      }
      grid[i] = best;
    }
    return grid;
  }

  function quantizeKMeans(pixels, palLabs, k, rng) {
    var P = pixels.length;
    var centers = [], chosen = {}, guard = 0;
    while (centers.length < k && guard < 10000) {
      guard++;
      var idx = Math.floor(rng() * P);
      if (!chosen[idx]) { chosen[idx] = true; centers.push(pixels[idx].slice()); }
    }
    var labels = new Int32Array(P), sums, cnts, nc, moved;
    for (var iter = 0; iter < 30; iter++) {
      for (var i = 0; i < P; i++) {
        var best = 0, bd = Infinity, p = pixels[i];
        for (var j = 0; j < k; j++) {
          var c = centers[j];
          var d = (p[0] - c[0]) * (p[0] - c[0]) + (p[1] - c[1]) * (p[1] - c[1]) + (p[2] - c[2]) * (p[2] - c[2]);
          if (d < bd) { bd = d; best = j; }
        }
        labels[i] = best;
      }
      sums = [], cnts = new Int32Array(k);
      for (var j = 0; j < k; j++) sums.push([0, 0, 0]);
      for (var i = 0; i < P; i++) {
        var l = labels[i], p = pixels[i];
        sums[l][0] += p[0]; sums[l][1] += p[1]; sums[l][2] += p[2]; cnts[l]++;
      }
      moved = 0;
      for (var j = 0; j < k; j++) {
        if (cnts[j] > 0) {
          nc = [sums[j][0] / cnts[j], sums[j][1] / cnts[j], sums[j][2] / cnts[j]];
          if (Math.abs(nc[0] - centers[j][0]) + Math.abs(nc[1] - centers[j][1]) + Math.abs(nc[2] - centers[j][2]) > 1e-9) moved++;
          centers[j] = nc;
        }
      }
      if (moved === 0) break;
    }
    var centerBead = new Int32Array(k);
    for (var j = 0; j < k; j++) {
      var best = 0, bd = Infinity, c = centers[j];
      for (var m = 0; m < palLabs.length; m++) {
        var pc = palLabs[m];
        var d = (c[0] - pc[0]) * (c[0] - pc[0]) + (c[1] - pc[1]) * (c[1] - pc[1]) + (c[2] - pc[2]) * (c[2] - pc[2]);
        if (d < bd) { bd = d; best = m; }
      }
      centerBead[j] = best;
    }
    var grid = new Int32Array(P);
    for (var i = 0; i < P; i++) grid[i] = centerBead[labels[i]];
    return grid;
  }

  function avgDeltaE(pixels, palLabs, grid) {
    var s = 0;
    for (var i = 0; i < pixels.length; i++) {
      var p = pixels[i], c = palLabs[grid[i]];
      s += Math.sqrt((p[0] - c[0]) * (p[0] - c[0]) + (p[1] - c[1]) * (p[1] - c[1]) + (p[2] - c[2]) * (p[2] - c[2]));
    }
    return s / pixels.length;
  }

  // ---------- 像素级后处理 ----------
  function luminanceHex(hex) {
    return 0.299 * parseInt(hex.slice(1, 3), 16) +
           0.587 * parseInt(hex.slice(3, 5), 16) +
           0.114 * parseInt(hex.slice(5, 7), 16);
  }

  // 去孤立杂点：只清"嵌在实心区里的散点"——周围 8 格无同色，且某一邻域色占绝对多数(≥半)。
  // 这样保护线条/纹理/过渡色：卡通插画这类本就平滑的图不会误删细节。
  function cleanIsolated(grid, N) {
    var out = new Int32Array(grid);
    for (var y = 0; y < N; y++) for (var x = 0; x < N; x++) {
      var i = y * N + x, c = grid[i];
      var same = 0, total = 0, counts = {};
      var y0 = Math.max(0, y - 1), y1 = Math.min(N - 1, y + 1);
      var x0 = Math.max(0, x - 1), x1 = Math.min(N - 1, x + 1);
      for (var yy = y0; yy <= y1; yy++) for (var xx = x0; xx <= x1; xx++) {
        var j = yy * N + xx;
        if (j === i) continue;
        total++;
        var cc = grid[j];
        if (cc === c) same++;
        counts[cc] = (counts[cc] || 0) + 1;
      }
      if (total >= 3 && same === 0) {
        var best = c, bc = 0;
        for (var kk in counts) { if (counts[kk] > bc) { bc = counts[kk]; best = +kk; } }
        if (bc >= Math.max(3, Math.ceil(total / 2))) out[i] = best;
      }
    }
    return out;
  }

  // 卡通描边：4 邻域明暗差超过阈值 → 涂成色板最深的颜色（形成轮廓线）
  function addOutline(grid, N, colors, threshold) {
    var lums = colors.map(function (c) { return luminanceHex(c[1]); });
    var dark = 0, minL = Infinity;
    lums.forEach(function (l, idx) { if (l < minL) { minL = l; dark = idx; } });
    var out = new Int32Array(grid);
    for (var y = 0; y < N; y++) for (var x = 0; x < N; x++) {
      var i = y * N + x, L = lums[grid[i]], md = 0;
      if (y > 0) md = Math.max(md, Math.abs(L - lums[grid[(y - 1) * N + x]]));
      if (y < N - 1) md = Math.max(md, Math.abs(L - lums[grid[(y + 1) * N + x]]));
      if (x > 0) md = Math.max(md, Math.abs(L - lums[grid[y * N + x - 1]]));
      if (x < N - 1) md = Math.max(md, Math.abs(L - lums[grid[y * N + x + 1]]));
      if (md > threshold) out[i] = dark;
    }
    return out;
  }

  // ---------- 主流程 ----------
  // data: 色板数据对象;  imageData: N*N 的 RGBA Uint8ClampedArray
  // post: {clean:bool, outline:bool, outlineThreshold:int} 可选的像素级后处理
  function processImage(data, brand, only, imageData, N, method, k, seed, post) {
    var colors = flattenPalette(data, brand, only);
    var P = N * N, pixels = new Array(P);
    for (var i = 0; i < P; i++) {
      pixels[i] = srgbToLab(imageData[i * 4], imageData[i * 4 + 1], imageData[i * 4 + 2]);
    }
    var palLabs = paletteLabs(colors);
    var grid = method === 'nearest'
      ? quantizeNearest(pixels, palLabs)
      : quantizeKMeans(pixels, palLabs, Math.min(k, P, colors.length), mulberry32(seed));
    if (post && post.clean) grid = cleanIsolated(grid, N);
    if (post && post.outline) grid = addOutline(grid, N, colors, post.outlineThreshold || 45);
    var avgDE = avgDeltaE(pixels, palLabs, grid);
    var countMap = {};
    for (var i = 0; i < P; i++) {
      countMap[grid[i]] = (countMap[grid[i]] || 0) + 1;
    }
    var counts = Object.keys(countMap).map(function (idx) {
      var i = +idx;
      return { idx: i, code: colors[i][0], hex: colors[i][1], count: countMap[i] };
    }).sort(function (a, b) { return b.count - a.count; });
    return { grid: grid, avgDE: avgDE, counts: counts, colors: colors, unique: counts.length };
  }

  return {
    srgbToLab: srgbToLab,
    mulberry32: mulberry32,
    flattenPalette: flattenPalette,
    paletteLabs: paletteLabs,
    quantizeNearest: quantizeNearest,
    quantizeKMeans: quantizeKMeans,
    avgDeltaE: avgDeltaE,
    luminanceHex: luminanceHex,
    cleanIsolated: cleanIsolated,
    addOutline: addOutline,
    processImage: processImage
  };
});
