/* zip.js — 纯 JS ZIP 打包（STORE 无压缩），浏览器 & node 通用，零依赖
   buildZip(entries) → Uint8Array
   entries: [{ name: 'xxx.png', data: Uint8Array }, ...]
   中文文件名走 UTF-8 标志位（bit 11），主流解压工具均可识别。 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ZipBuilder = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var CRC_TABLE = null;
  function crcTable() {
    if (CRC_TABLE) return CRC_TABLE;
    var t = new Int32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c;
    }
    CRC_TABLE = t;
    return t;
  }

  function crc32(bytes) {
    var t = crcTable(), c = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) c = t[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  function dosDateTime() {
    var d = new Date();
    var time = ((d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1)) & 0xFFFF;
    var date = ((((d.getFullYear() - 1980) & 0x7F) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()) & 0xFFFF;
    return { time: time, date: date };
  }

  function buildZip(entries) {
    var enc = new TextEncoder();
    var dt = dosDateTime();
    var locals = [], centrals = [], offset = 0;
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      var name = enc.encode(e.name);
      var data = e.data;
      var size = data.length, crc = crc32(data);

      // 本地文件头
      var lh = new Uint8Array(30 + name.length);
      var dv = new DataView(lh.buffer);
      dv.setUint32(0, 0x04034b50, true);
      dv.setUint16(4, 20, true);        // version needed
      dv.setUint16(6, 0x0800, true);    // UTF-8 文件名标志
      dv.setUint16(8, 0, true);         // STORE（无压缩）
      dv.setUint16(10, dt.time, true);
      dv.setUint16(12, dt.date, true);
      dv.setUint32(14, crc, true);
      dv.setUint32(18, size, true);
      dv.setUint32(22, size, true);
      dv.setUint16(26, name.length, true);
      dv.setUint16(28, 0, true);
      lh.set(name, 30);
      locals.push(lh); locals.push(data);

      // 中央目录条目
      var ce = new Uint8Array(46 + name.length);
      var dv2 = new DataView(ce.buffer);
      dv2.setUint32(0, 0x02014b50, true);
      dv2.setUint16(4, 20, true);
      dv2.setUint16(6, 20, true);
      dv2.setUint16(8, 0x0800, true);
      dv2.setUint16(10, 0, true);
      dv2.setUint16(12, dt.time, true);
      dv2.setUint16(14, dt.date, true);
      dv2.setUint32(16, crc, true);
      dv2.setUint32(20, size, true);
      dv2.setUint32(24, size, true);
      dv2.setUint16(28, name.length, true);
      dv2.setUint16(30, 0, true);
      dv2.setUint16(32, 0, true);
      dv2.setUint16(34, 0, true);
      dv2.setUint16(36, 0, true);
      dv2.setUint32(38, 0, true);
      dv2.setUint32(42, offset, true);
      ce.set(name, 46);
      centrals.push(ce);

      offset += lh.length + data.length;
    }

    var cdSize = 0;
    centrals.forEach(function (p) { cdSize += p.length; });
    var eocd = new Uint8Array(22);
    var dv3 = new DataView(eocd.buffer);
    dv3.setUint32(0, 0x06054b50, true);
    dv3.setUint16(8, entries.length, true);
    dv3.setUint16(10, entries.length, true);
    dv3.setUint32(12, cdSize, true);
    dv3.setUint32(16, offset, true);

    var total = offset + cdSize + 22;
    var out = new Uint8Array(total);
    var pos = 0;
    for (var i = 0; i < locals.length; i++) { out.set(locals[i], pos); pos += locals[i].length; }
    for (var i = 0; i < centrals.length; i++) { out.set(centrals[i], pos); pos += centrals[i].length; }
    out.set(eocd, pos);
    return out;
  }

  return { buildZip: buildZip, crc32: crc32 };
});
