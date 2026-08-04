/* app.js — 拼豆图纸生成器 UI 逻辑 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };

  // ---- DOM ----
  var dropZone = $('drop-zone');
  var fileInput = $('file-input');
  var gridSelect = $('grid-select');
  var gridCustomWrap = $('grid-custom-wrap');
  var gridCustom = $('grid-custom');
  var brandSelect = $('brand-select');
  var presetSelect = $('preset-select');
  var subsetInput = $('subset-input');
  var methodKmeans = $('method-kmeans');
  var methodNearest = $('method-nearest');
  var kInput = $('k-input');
  var labelCheck = $('label-check');
  var cleanCheck = $('clean-check');
  var outlineCheck = $('outline-check');
  var outlineThresh = $('outline-thresh');
  var genBtn = $('gen-btn');
  var previewCanvas = $('preview-canvas');
  var specCanvas = $('spec-canvas');
  var metricsEl = $('metrics');
  var usageTableBody = $('usage-body');
  var origThumb = $('orig-thumb');
  var origWrap = $('orig-wrap');
  var origName = $('orig-name');
  var downloadPreview = $('download-preview');
  var downloadSpec = $('download-spec');
  var downloadCsv = $('download-csv');
  var downloadAll = $('download-all');
  var downloadZip = $('download-zip');

  var SEED = 42;
  var MAX_GRID = 60;
  var currentFile = null;   // 当前上传的文件（点击选择 / 拖拽 都记录到这里）
  var current = null;       // 最近一次结果 {grid, counts, colors, unique, avgDE, N}
  var fileName = '';

  // 把任何运行期错误显示到页面上，避免"点了没反应"
  window.addEventListener('error', function (e) {
    metricsEl.innerHTML = '<span class="bad">发生错误：' + e.message + '</span>';
  });

  function showStatus(msg, isError) {
    metricsEl.innerHTML = isError
      ? '<span class="bad">' + msg + '</span>'
      : msg;
  }

  function init() {
    try {
      if (typeof window.BeadsCore !== 'function' && typeof window.BeadsCore !== 'object') {
        throw new Error('core.js 未加载，请确认它与本页面在同一目录');
      }
      if (!window.PALETTES) {
        throw new Error('palettes.js 未加载，请确认它与本页面在同一目录');
      }
      if (!window.ZipBuilder) {
        throw new Error('zip.js 未加载，请确认它与本页面在同一目录');
      }
      if (!window.BeadsEnhance) {
        throw new Error('enhance.js 未加载，请确认它与本页面在同一目录');
      }
      // 预设下拉
      window.BeadsEnhance.PRESET_ORDER.forEach(function (name) {
        var opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        presetSelect.appendChild(opt);
      });
      presetSelect.value = '通用';
      // 色板下拉
      Object.keys(window.PALETTES).forEach(function (key) {
        var opt = document.createElement('option');
        opt.value = key;
        var labels = { mard291: 'MARD 全色 291', mard221: 'MARD 标准 221', artkal: 'Artkal 176',
                       perler: 'Perler 110', hama: 'Hama 89', artkalMini: 'Artkal Mini 207' };
        opt.textContent = labels[key] || key;
        brandSelect.appendChild(opt);
      });
      brandSelect.value = 'mard291';
      wireEvents();
    } catch (e) {
      showStatus('页面初始化失败：' + e.message, true);
    }
  }

  function wireEvents() {
    // 网格选择：预设 / 自定义
    gridSelect.addEventListener('change', function () {
      gridCustomWrap.style.display = gridSelect.value === 'custom' ? 'inline-block' : 'none';
    });
    // 上传
    fileInput.addEventListener('change', function () { handleFile(fileInput.files[0]); });
    dropZone.addEventListener('click', function () { fileInput.click(); });
    ['dragover', 'dragenter'].forEach(function (ev) {
      dropZone.addEventListener(ev, function (e) { e.preventDefault(); dropZone.classList.add('dragging'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      dropZone.addEventListener(ev, function (e) { e.preventDefault(); dropZone.classList.remove('dragging'); });
    });
    dropZone.addEventListener('drop', function (e) {
      var f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) handleFile(f);
    });
    genBtn.addEventListener('click', generate);
    ['change', 'input'].forEach(function (ev) {
      [gridSelect, gridCustom, brandSelect, presetSelect, subsetInput, methodKmeans, methodNearest, kInput, labelCheck,
       cleanCheck, outlineCheck, outlineThresh]
        .forEach(function (el) { el.addEventListener(ev, generate); });
    });
    // 下载
    downloadPreview.addEventListener('click', function () {
      if (!current) return;
      triggerDownload(previewCanvas.toDataURL('image/png'), baseName() + '_preview.png');
    });
    downloadSpec.addEventListener('click', function () {
      if (!current) return;
      triggerDownload(specCanvas.toDataURL('image/png'), baseName() + '_spec.png');
    });
    downloadCsv.addEventListener('click', function () {
      if (!current) return;
      downloadCsvFile(baseName() + '_usage.csv');
    });
    downloadAll.addEventListener('click', function () {
      if (!current) {
        showStatus('请先上传照片并生成图纸，再一键保存。', true);
        return;
      }
      var base = baseName();
      // 同步生成所有文件，确保在同一次用户手势内触发，避免被浏览器拦截
      triggerDownload(previewCanvas.toDataURL('image/png'), base + '_preview.png');
      triggerDownload(specCanvas.toDataURL('image/png'), base + '_spec.png');
      downloadCsvFile(base + '_usage.csv');
    });
    downloadZip.addEventListener('click', function () {
      if (!current) {
        showStatus('请先上传照片并生成图纸，再下载 ZIP 素材包。', true);
        return;
      }
      var base = baseName();
      // 全部同步生成，保证在同一次用户手势内触发下载
      var previewBytes = dataURLToBytes(previewCanvas.toDataURL('image/png'));
      var specBytes = dataURLToBytes(specCanvas.toDataURL('image/png'));
      var csv = 'color_code,hex,count\n' + current.counts.map(function (c) {
        return c.code + ',' + c.hex + ',' + c.count;
      }).join('\n') + '\n';
      var zip = window.ZipBuilder.buildZip([
        { name: base + '_preview.png', data: previewBytes },
        { name: base + '_spec.png', data: specBytes },
        { name: base + '_usage.csv', data: new TextEncoder().encode(csv) }
      ]);
      var url = URL.createObjectURL(new Blob([zip], { type: 'application/zip' }));
      triggerDownload(url, base + '_素材包.zip');
      setTimeout(function () { URL.revokeObjectURL(url); }, 3000);
      showStatus('已打包 ' + (zip.length / 1024).toFixed(1) + ' KB：预览图 + 施工图 + 用量清单。');
    });
  }

  // dataURL("data:image/png;base64,xxxx") → Uint8Array（同步）
  function dataURLToBytes(dataURL) {
    var bin = atob(dataURL.split(',')[1]);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }

  function baseName() { return fileName || 'pattern'; }

  function triggerDownload(href, filename) {
    var a = document.createElement('a');
    a.href = href; a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function downloadCsvFile(filename) {
    var csv = 'color_code,hex,count\n' + current.counts.map(function (c) {
      return c.code + ',' + c.hex + ',' + c.count;
    }).join('\n') + '\n';
    var url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    triggerDownload(url, filename);
    setTimeout(function () { URL.revokeObjectURL(url); }, 3000);
  }

  function handleFile(file) {
    if (!file) return;
    currentFile = file;   // 关键：点击选择 / 拖拽都记录，generate 统一从这里取
    fileName = file.name.replace(/\.[^.]+$/, '');
    origName.textContent = file.name;
    var url = URL.createObjectURL(file);
    origThumb.onload = function () { URL.revokeObjectURL(url); };
    origThumb.src = url;
    origWrap.style.display = 'block';
    generate();   // 上传后自动生成
  }

  // ---- 读取图片 → 缩放到 N×N RGBA（带超时，防止卡在"生成中"） ----
  function loadImage(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      var done = false;
      var timer = setTimeout(function () {
        if (!done) { done = true; reject(new Error('图片解码超时（15秒）')); }
      }, 15000);
      img.onload = function () {
        if (done) return;
        done = true; clearTimeout(timer);
        URL.revokeObjectURL(url);
        resolve(img);
      };
      img.onerror = function () {
        if (done) return;
        done = true; clearTimeout(timer);
        reject(new Error('无法读取该图片（格式不支持？）'));
      };
      img.src = url;
    });
  }

  function readImageData(file, N) {
    return loadImage(file).then(function (img) {
      var side = Math.min(img.naturalWidth, img.naturalHeight);
      var sx = (img.naturalWidth - side) / 2;
      var sy = (img.naturalHeight - side) / 2;
      var c = document.createElement('canvas');
      c.width = N; c.height = N;
      var ctx = c.getContext('2d');
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(img, sx, sy, side, side, 0, 0, N, N);
      return ctx.getImageData(0, 0, N, N).data;
    });
  }

  // ---- 主流程 ----
  async function generate() {
    if (!currentFile) {
      showStatus('请先上传照片：点击上方虚线区域选择，或直接拖拽照片进来。', true);
      return;
    }
    genBtn.disabled = true;
    genBtn.textContent = '生成中…';
    showStatus('正在生成，请稍候…');
    try {
      var N = gridSize();
      var brand = brandSelect.value;
      var only = subsetInput.value.trim() || null;
      var method = methodNearest.checked ? 'nearest' : 'kmeans';
      var k = parseInt(kInput.value, 10) || 16;
      var preset = presetSelect.value;
      var rawRGBA, steps = [];
      if (preset === '通用') {
        rawRGBA = await readImageData(currentFile, N);
      } else {
        var img = await loadImage(currentFile);
        var enhanced = window.BeadsEnhance.processImageWithPreset(img, preset, N, 512);
        rawRGBA = enhanced.imageData.data;
        steps = enhanced.steps;
      }
      var post = null;
      if (cleanCheck.checked || outlineCheck.checked) {
        post = {
          clean: cleanCheck.checked,
          outline: outlineCheck.checked,
          outlineThreshold: parseInt(outlineThresh.value, 10) || 45
        };
      }
      var res = window.BeadsCore.processImage(window.PALETTES, brand, only, rawRGBA, N, method, k, SEED, post);
      var postSteps = [];
      if (post && post.clean) postSteps.push('去杂点');
      if (post && post.outline) postSteps.push('卡通描边');
      current = { grid: res.grid, counts: res.counts, colors: res.colors,
                  unique: res.unique, avgDE: res.avgDE, N: N, brand: brand,
                  preset: preset, steps: steps, postSteps: postSteps };
      renderAll();
    } catch (e) {
      showStatus('出错：' + e.message, true);
    }
    genBtn.disabled = false;
    genBtn.textContent = '重新生成';
  }

  function gridSize() {
    var v = gridSelect.value;
    var n = v === 'custom' ? parseInt(gridCustom.value, 10) : parseInt(v, 10);
    if (!n || n < 1) n = 60;
    if (n > MAX_GRID) n = MAX_GRID;
    return n;
  }

  // ---- 渲染 ----
  function renderAll() {
    var g = current;
    drawPreview(previewCanvas.getContext('2d'), previewCanvas, g);
    drawSpec(specCanvas.getContext('2d'), specCanvas, g);
    // 指标
    var outlined = g.postSteps && g.postSteps.indexOf('卡通描边') >= 0;
    var warn = g.avgDE > 15 && !outlined;
    var verdict;
    if (warn) {
      verdict = '<span class="bad">(超过建议阈值 15，建议加大网格)</span>';
    } else if (outlined && g.avgDE > 15) {
      verdict = '<span class="good">(ΔE 含卡通描边艺术化改动，属正常)</span>';
    } else {
      verdict = '<span class="good">(达标，可接受)</span>';
    }
    var presetInfo = g.preset && g.preset !== '通用'
      ? ' ｜ 预设 <b>' + g.preset + '</b>' + (g.steps && g.steps.length ? '（' + g.steps.join('、') + '）' : '')
      : '';
    var postInfo = g.postSteps && g.postSteps.length ? ' ｜ 后处理 <b>' + g.postSteps.join('、') + '</b>' : '';
    metricsEl.innerHTML = '网格 <b>' + g.N + '×' + g.N + '</b> = <b>' + (g.N * g.N) +
      '</b> 颗豆 ｜ 用色 <b>' + g.unique + '</b> 种 ｜ 平均色差 ΔE = <b>' + g.avgDE.toFixed(1) + '</b> ' +
      verdict + presetInfo + postInfo;
    // 用量表
    usageTableBody.innerHTML = '';
    g.counts.forEach(function (c) {
      var tr = document.createElement('tr');
      var sw = document.createElement('td');
      sw.innerHTML = '<span class="swatch" style="background:' + c.hex + '"></span>' + c.code;
      var hx = document.createElement('td'); hx.textContent = c.hex;
      var cn = document.createElement('td'); cn.textContent = c.count;
      tr.appendChild(sw); tr.appendChild(hx); tr.appendChild(cn);
      usageTableBody.appendChild(tr);
    });
    downloadPreview.disabled = false;
    downloadSpec.disabled = false;
    downloadCsv.disabled = false;
    downloadAll.disabled = false;
    downloadZip.disabled = false;
  }

  function luminance(hex) {
    var r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
    return 0.299 * r + 0.587 * g + 0.114 * b;
  }
  function textColor(hex) { return luminance(hex) > 150 ? '#141414' : '#ffffff'; }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); }
    else {
      ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r);
      ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r);
    }
    ctx.closePath(); ctx.fill();
  }

  function drawPreview(ctx, canvas, g) {
    var N = g.N, cell = 14, gap = Math.max(2, Math.round(cell / 6)), pad = gap;
    var labels = labelCheck.checked;
    var size = N * cell + gap * (N - 1) + pad * 2;
    canvas.width = size; canvas.height = size;
    ctx.clearRect(0, 0, size, size);
    ctx.fillStyle = '#f0f0f0'; ctx.fillRect(0, 0, size, size);
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    var font = labels ? Math.max(7, Math.floor(cell / 2.6)) : 0;
    for (var r = 0; r < N; r++) for (var c = 0; c < N; c++) {
      var idx = g.grid[r * N + c], hex = g.colors[idx][1];
      var x0 = pad + c * (cell + gap), y0 = pad + r * (cell + gap);
      ctx.fillStyle = hex;
      roundRect(ctx, x0, y0, cell, cell, cell * 0.22);
      if (labels) {
        ctx.fillStyle = textColor(hex);
        ctx.font = font + 'px sans-serif';
        ctx.fillText(g.colors[idx][0], x0 + cell / 2, y0 + cell / 2 + 0.5);
      }
    }
  }

  function drawSpec(ctx, canvas, g) {
    var N = g.N;
    var cell = N <= 30 ? 46 : (N <= 49 ? 30 : 26);
    var gap = 2, ruler = 16;
    var gridPx = N * cell + gap * (N - 1);
    var W = ruler * 2 + gridPx;
    var legendTop = ruler + gridPx + 24;
    var H = legendTop + g.counts.length * 20 + 24;
    canvas.width = W; canvas.height = H;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H);
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    var labelFont = Math.max(8, Math.floor(cell / 4));
    for (var r = 0; r < N; r++) for (var c = 0; c < N; c++) {
      var idx = g.grid[r * N + c], hex = g.colors[idx][1];
      var x0 = ruler + c * (cell + gap), y0 = ruler + r * (cell + gap);
      ctx.fillStyle = hex; ctx.fillRect(x0, y0, cell, cell);
      ctx.strokeStyle = '#666'; ctx.lineWidth = 1; ctx.strokeRect(x0 + 0.5, y0 + 0.5, cell - 1, cell - 1);
      ctx.fillStyle = textColor(hex);
      ctx.font = labelFont + 'px sans-serif';
      ctx.fillText(g.colors[idx][0], x0 + cell / 2, y0 + cell / 2 + 0.5);
    }
    // 坐标刻度
    ctx.fillStyle = '#666'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
    for (var i = 0; i < N; i += 5) {
      ctx.fillText(String(i), ruler + i * (cell + gap) + cell / 2, ruler - 7);
      ctx.fillText(String(i), ruler - 8, ruler + i * (cell + gap) + cell / 2);
    }
    // 图例
    ctx.textAlign = 'left'; ctx.font = '13px sans-serif';
    ctx.fillStyle = '#1e1e1e';
    ctx.fillText('用量清单（共 ' + (N * N) + ' 颗豆）', ruler, legendTop - 8);
    for (var i = 0; i < g.counts.length; i++) {
      var c = g.counts[i], y = legendTop + i * 20;
      ctx.fillStyle = c.hex; ctx.fillRect(ruler, y + 2, 16, 16);
      ctx.strokeStyle = '#444'; ctx.lineWidth = 1; ctx.strokeRect(ruler + 0.5, y + 2.5, 15, 15);
      ctx.fillStyle = '#1e1e1e';
      ctx.fillText(c.code + '  ' + c.hex + '  ×' + c.count, ruler + 22, y + 10);
    }
  }

  init();
})();
