/* matting.js — 本地背景抠图（与 scripts/matting.py 对齐，无 GrabCut/人脸时用 corner/saliency）
   浏览器: window.BeadsMatting
   node: require('./matting.js') */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BeadsMatting = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function cornersSimilar(rgba, w, h) {
    var s = Math.max(4, Math.min(Math.floor(Math.min(w, h) / 16), 32));
    var patches = [
      [0, 0], [w - s, 0], [0, h - s], [w - s, h - s]
    ];
    var means = [], maxStd = 0;
    for (var p = 0; p < 4; p++) {
      var sx = patches[p][0], sy = patches[p][1];
      var sr = 0, sg = 0, sb = 0, n = 0;
      var vals = [];
      for (var y = sy; y < sy + s; y++) for (var x = sx; x < sx + s; x++) {
        var i = (y * w + x) * 4;
        sr += rgba[i]; sg += rgba[i + 1]; sb += rgba[i + 2];
        vals.push([rgba[i], rgba[i + 1], rgba[i + 2]]);
        n++;
      }
      var mr = sr / n, mg = sg / n, mb = sb / n;
      means.push([mr, mg, mb]);
      var acc = 0;
      for (var k = 0; k < vals.length; k++) {
        var dr = vals[k][0] - mr, dg = vals[k][1] - mg, db = vals[k][2] - mb;
        acc += Math.sqrt(dr * dr + dg * dg + db * db);
      }
      maxStd = Math.max(maxStd, acc / vals.length);
    }
    if (maxStd > 18) return { ok: false, bg: means[0] };
    var maxPair = 0;
    for (var i = 0; i < 4; i++) for (var j = i + 1; j < 4; j++) {
      var d0 = means[i][0] - means[j][0], d1 = means[i][1] - means[j][1], d2 = means[i][2] - means[j][2];
      maxPair = Math.max(maxPair, Math.sqrt(d0 * d0 + d1 * d1 + d2 * d2));
    }
    if (maxPair > 22) return { ok: false, bg: means[0] };
    var bg = [
      (means[0][0] + means[1][0] + means[2][0] + means[3][0]) / 4,
      (means[0][1] + means[1][1] + means[2][1] + means[3][1]) / 4,
      (means[0][2] + means[1][2] + means[2][2] + means[3][2]) / 4
    ];
    return { ok: true, bg: bg };
  }

  function cornerFlood(rgba, w, h, thr) {
    thr = thr || 28;
    var sim = cornersSimilar(rgba, w, h);
    if (!sim.ok) return null;
    var bg = sim.bg;
    var dist = new Float32Array(w * h);
    for (var i = 0; i < w * h; i++) {
      var o = i * 4;
      var dr = rgba[o] - bg[0], dg = rgba[o + 1] - bg[1], db = rgba[o + 2] - bg[2];
      dist[i] = Math.sqrt(dr * dr + dg * dg + db * db);
    }
    var visited = new Uint8Array(w * h);
    var q = [];
    function trySeed(x, y) {
      var i = y * w + x;
      if (!visited[i] && dist[i] <= thr) { visited[i] = 1; q.push(i); }
    }
    for (var x = 0; x < w; x++) { trySeed(x, 0); trySeed(x, h - 1); }
    for (var y = 0; y < h; y++) { trySeed(0, y); trySeed(w - 1, y); }
    var head = 0;
    while (head < q.length) {
      var i = q[head++];
      var x = i % w, y = (i / w) | 0;
      var nbs = [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]];
      for (var t = 0; t < 4; t++) {
        var nx = nbs[t][0], ny = nbs[t][1];
        if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
        var ni = ny * w + nx;
        if (!visited[ni] && dist[ni] <= thr * 1.15) {
          visited[ni] = 1;
          q.push(ni);
        }
      }
    }
    var fg = 0, mask = new Float32Array(w * h);
    for (var i = 0; i < w * h; i++) {
      mask[i] = visited[i] ? 0 : 1;
      fg += mask[i];
    }
    var ratio = fg / (w * h);
    if (ratio < 0.02 || ratio > 0.98) return null;
    return mask;
  }

  function saliencySoft(rgba, w, h) {
    var gray = new Float32Array(w * h);
    for (var i = 0; i < w * h; i++) {
      var o = i * 4;
      gray[i] = 0.299 * rgba[o] + 0.587 * rgba[o + 1] + 0.114 * rgba[o + 2];
    }
    var edge = new Float32Array(w * h);
    var maxE = 0;
    for (var y = 1; y < h - 1; y++) for (var x = 1; x < w - 1; x++) {
      var p = y * w + x;
      var gx = gray[p + 1] - gray[p - 1];
      var gy = gray[p + w] - gray[p - w];
      edge[p] = Math.sqrt(gx * gx + gy * gy);
      if (edge[p] > maxE) maxE = edge[p];
    }
    var sx = 0, sy = 0, sw = 0;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var e = edge[y * w + x] + 1e-6;
      sx += x * e; sy += y * e; sw += e;
    }
    var cx = sx / sw, cy = sy / sw;
    // border mean
    var br = 0, bg = 0, bb = 0, bn = 0;
    function addBorder(x, y) {
      var o = (y * w + x) * 4;
      br += rgba[o]; bg += rgba[o + 1]; bb += rgba[o + 2]; bn++;
    }
    for (var x = 0; x < w; x++) { addBorder(x, 0); addBorder(x, h - 1); }
    for (var y = 0; y < h; y++) { addBorder(0, y); addBorder(w - 1, y); }
    br /= bn; bg /= bn; bb /= bn;
    var maxC = 0;
    var cdist = new Float32Array(w * h);
    for (var i = 0; i < w * h; i++) {
      var o = i * 4;
      var dr = rgba[o] - br, dg = rgba[o + 1] - bg, db = rgba[o + 2] - bb;
      cdist[i] = Math.sqrt(dr * dr + dg * dg + db * db);
      if (cdist[i] > maxC) maxC = cdist[i];
    }
    var mask = new Float32Array(w * h);
    var fg = 0;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var i = y * w + x;
      var dist = Math.sqrt(Math.pow((x - cx) / w, 2) + Math.pow((y - cy) / h, 2));
      var eN = edge[i] / (maxE + 1e-6);
      var cN = cdist[i] / (maxC + 1e-6);
      var score = 0.5 * (0.55 * (1 - Math.min(dist / 0.55, 1)) + 0.45 * eN) + 0.5 * cN;
      mask[i] = score > 0.35 ? 1 : 0;
      fg += mask[i];
    }
    if (fg / (w * h) < 0.05) {
      for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
        var dist = Math.sqrt(Math.pow((x - cx) / w, 2) + Math.pow((y - cy) / h, 2));
        mask[y * w + x] = dist < 0.35 ? 1 : 0;
      }
    }
    return mask;
  }

  function applyMaskToImageData(imageData, mask) {
    var d = imageData.data;
    for (var i = 0; i < mask.length; i++) {
      d[i * 4 + 3] = mask[i] > 0.5 ? 255 : 0;
    }
    return imageData;
  }

  function autoMatte(imageData, w, h, mode) {
    mode = mode || 'auto';
    var rgba = imageData.data;
    var mask = null, used = mode;
    if (mode === 'auto' || mode === 'corner') {
      mask = cornerFlood(rgba, w, h);
      if (mask) used = 'corner_flood';
    }
    if (!mask && (mode === 'auto' || mode === 'grabcut' || mode === 'saliency')) {
      // 浏览器无 OpenCV GrabCut：grabcut 请求时退到 saliency
      mask = saliencySoft(rgba, w, h);
      used = mode === 'grabcut' ? 'saliency_soft(no-opencv)' : 'saliency_soft';
    }
    applyMaskToImageData(imageData, mask);
    return { imageData: imageData, mode: used };
  }

  /** 对 HTMLImageElement / ImageBitmap 抠图，返回带 alpha 的 ImageData（工作尺寸） */
  function matteImage(img, workingSize, mode) {
    workingSize = workingSize || 512;
    mode = mode || 'auto';
    var c = document.createElement('canvas');
    c.width = c.height = workingSize;
    var ctx = c.getContext('2d');
    // 居中裁方再画
    var ow = img.naturalWidth || img.width, oh = img.naturalHeight || img.height;
    var side = Math.min(ow, oh);
    var sx = (ow - side) / 2, sy = (oh - side) / 2;
    ctx.drawImage(img, sx, sy, side, side, 0, 0, workingSize, workingSize);
    var id = ctx.getImageData(0, 0, workingSize, workingSize);
    return autoMatte(id, workingSize, workingSize, mode);
  }

  /** 直接对已有 ImageData 抠图 */
  function matteImageData(imageData, w, h, mode) {
    return autoMatte(imageData, w, h, mode || 'auto');
  }

  return {
    cornersSimilar: cornersSimilar,
    cornerFlood: cornerFlood,
    saliencySoft: saliencySoft,
    autoMatte: autoMatte,
    matteImage: matteImage,
    matteImageData: matteImageData
  };
});
