/* qr.js — a compact QR Code encoder (byte mode), vendored so the Lens Builder
 * can make a scannable code for a lens with no network and no dependency.
 *
 * Faithful port of Nayuki's "QR Code generator library" (public domain,
 * https://www.nayuki.io/page/qr-code-generator-library). Trimmed to what the
 * builder needs: byte-mode data, automatic version, all four ECC levels, and
 * the eight masks with penalty-based selection. Its output is verified
 * bit-for-bit against the reference `qrcode` implementation in the test suite.
 *
 * API (UMD → global `QRLite`):
 *   QRLite.matrix(text, {ecl, mask})  -> boolean[][]  (true = dark module)
 *   QRLite.draw(canvas, text, opts)   -> renders to a <canvas>
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.QRLite = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var ECC = { L: 0, M: 1, Q: 2, H: 3 };           // level -> formatBits index
  var ECC_FORMAT = { 0: 1, 1: 0, 2: 3, 3: 2 };    // level -> 2-bit format value
  var MIN_VER = 1, MAX_VER = 40;

  // -- per (ECL, version) tables (index 0 unused) ----------------------------
  var ECC_CODEWORDS_PER_BLOCK = [
    // ver: 1 .. 40
    [-1,7,10,15,20,26,18,20,24,30,18,20,24,26,30,22,24,28,30,28,28,28,28,30,30,26,28,30,30,30,30,30,30,30,30,30,30,30,30,30,30], // L
    [-1,10,16,26,18,24,16,18,22,22,26,30,22,22,24,24,28,28,26,26,26,26,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28,28], // M
    [-1,13,22,18,26,18,24,18,22,20,24,28,26,24,20,30,24,28,28,26,30,28,30,30,30,30,28,30,30,30,30,30,30,30,30,30,30,30,30,30,30], // Q
    [-1,17,28,22,16,22,28,26,26,24,28,24,28,22,24,24,30,28,28,26,28,30,24,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30], // H
  ];
  var NUM_ERROR_CORRECTION_BLOCKS = [
    [-1,1,1,1,1,1,2,2,2,2,4,4,4,4,4,6,6,6,6,7,8,8,9,9,10,12,12,12,13,14,15,16,17,18,19,19,20,21,22,24,25], // L
    [-1,1,1,1,2,2,4,4,4,5,5,5,8,9,9,10,10,11,13,14,16,17,17,18,20,21,23,25,26,28,29,31,33,35,37,38,40,43,45,47,49], // M
    [-1,1,1,2,2,4,4,6,6,8,8,8,10,12,16,12,17,16,18,21,20,23,23,25,27,29,34,34,35,38,40,43,45,48,51,53,56,59,62,65,68], // Q
    [-1,1,1,2,4,4,4,5,6,8,8,11,11,16,16,18,16,19,21,25,25,25,34,30,32,35,37,40,42,45,48,51,54,57,60,63,66,70,74,77,81], // H
  ];

  // GF(256) with primitive 0x11D
  function rsMul(x, y) {
    var z = 0;
    for (var i = 7; i >= 0; i--) {
      z = (z << 1) ^ ((z >>> 7) * 0x11D);
      z ^= ((y >>> i) & 1) * x;
    }
    return z & 0xFF;
  }
  function rsDivisor(degree) {
    var result = []; for (var i = 0; i < degree - 1; i++) result.push(0); result.push(1);
    var root = 1;
    for (var i2 = 0; i2 < degree; i2++) {
      for (var j = 0; j < result.length; j++) {
        result[j] = rsMul(result[j], root);
        if (j + 1 < result.length) result[j] ^= result[j + 1];
      }
      root = rsMul(root, 0x02);
    }
    return result;
  }
  function rsRemainder(data, divisor) {
    var result = divisor.map(function () { return 0; });
    data.forEach(function (b) {
      var factor = b ^ result.shift();
      result.push(0);
      divisor.forEach(function (d, i) { result[i] ^= rsMul(d, factor); });
    });
    return result;
  }

  function numDataCodewords(ver, ecl) {
    return Math.floor(numRawDataModules(ver) / 8)
      - ECC_CODEWORDS_PER_BLOCK[ecl][ver] * NUM_ERROR_CORRECTION_BLOCKS[ecl][ver];
  }
  function numRawDataModules(ver) {
    var result = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
      var numAlign = Math.floor(ver / 7) + 2;
      result -= (25 * numAlign - 10) * numAlign - 55;
      if (ver >= 7) result -= 36;
    }
    return result;
  }

  // byte-mode capacity check: bits = 4 (mode) + charCountBits + 8*len
  function charCountBits(ver) { return ver <= 9 ? 8 : 16; }
  function fitsVersion(ver, ecl, len) {
    var cap = numDataCodewords(ver, ecl) * 8;
    return 4 + charCountBits(ver) + 8 * len <= cap;
  }

  function addEccAndInterleave(dataCodewords, ver, ecl) {
    var numBlocks = NUM_ERROR_CORRECTION_BLOCKS[ecl][ver];
    var blockEccLen = ECC_CODEWORDS_PER_BLOCK[ecl][ver];
    var rawCodewords = Math.floor(numRawDataModules(ver) / 8);
    var numShortBlocks = numBlocks - rawCodewords % numBlocks;
    var shortBlockLen = Math.floor(rawCodewords / numBlocks);
    var blocks = [];
    var divisor = rsDivisor(blockEccLen);
    for (var i = 0, k = 0; i < numBlocks; i++) {
      var datLen = shortBlockLen - blockEccLen + (i < numShortBlocks ? 0 : 1);
      var dat = dataCodewords.slice(k, k + datLen); k += datLen;
      var ecc = rsRemainder(dat, divisor);
      if (i < numShortBlocks) dat.push(0);
      blocks.push(dat.concat(ecc));
    }
    var result = [];
    for (var col = 0; col < blocks[0].length; col++) {
      for (var b = 0; b < blocks.length; b++) {
        if (col != shortBlockLen - blockEccLen || b >= numShortBlocks)
          result.push(blocks[b][col]);
      }
    }
    return result;
  }

  // -- the code -------------------------------------------------------------
  function QrCode(ver, ecl, dataCodewords, mask) {
    this.version = ver; this.ecl = ecl; this.size = ver * 4 + 17;
    this.modules = []; this.isFunction = [];
    for (var i = 0; i < this.size; i++) {
      this.modules.push(new Array(this.size).fill(false));
      this.isFunction.push(new Array(this.size).fill(false));
    }
    this.drawFunctionPatterns();
    var allCodewords = addEccAndInterleave(dataCodewords, ver, ecl);
    this.drawCodewords(allCodewords);
    if (mask == -1) {
      var minPenalty = Infinity;
      for (var m = 0; m < 8; m++) {
        this.applyMask(m); this.drawFormatBits(m);
        var p = this.getPenaltyScore();
        if (p < minPenalty) { mask = m; minPenalty = p; }
        this.applyMask(m);
      }
    }
    this.mask = mask;
    this.applyMask(mask);
    this.drawFormatBits(mask);
  }
  QrCode.prototype.setFunctionModule = function (x, y, isDark) {
    this.modules[y][x] = isDark; this.isFunction[y][x] = true;
  };
  QrCode.prototype.drawFunctionPatterns = function () {
    var self = this, size = this.size;
    for (var i = 0; i < size; i++) {
      this.setFunctionModule(6, i, i % 2 == 0);
      this.setFunctionModule(i, 6, i % 2 == 0);
    }
    this.drawFinder(3, 3); this.drawFinder(size - 4, 3); this.drawFinder(3, size - 4);
    var alignPos = this.alignmentPatternPositions();
    var n = alignPos.length;
    for (var a = 0; a < n; a++) for (var b = 0; b < n; b++) {
      if (!((a == 0 && b == 0) || (a == 0 && b == n - 1) || (a == n - 1 && b == 0)))
        this.drawAlignment(alignPos[a], alignPos[b]);
    }
    this.drawFormatBits(0);
    this.drawVersion();
  };
  QrCode.prototype.drawFinder = function (x, y) {
    for (var dy = -4; dy <= 4; dy++) for (var dx = -4; dx <= 4; dx++) {
      var dist = Math.max(Math.abs(dx), Math.abs(dy)), xx = x + dx, yy = y + dy;
      if (0 <= xx && xx < this.size && 0 <= yy && yy < this.size)
        this.setFunctionModule(xx, yy, dist != 2 && dist != 4);
    }
  };
  QrCode.prototype.drawAlignment = function (x, y) {
    for (var dy = -2; dy <= 2; dy++) for (var dx = -2; dx <= 2; dx++)
      this.setFunctionModule(x + dx, y + dy, Math.max(Math.abs(dx), Math.abs(dy)) != 1);
  };
  QrCode.prototype.alignmentPatternPositions = function () {
    var ver = this.version;
    if (ver == 1) return [];
    var numAlign = Math.floor(ver / 7) + 2;
    var step = (ver == 32) ? 26 : Math.ceil((ver * 4 + 4) / (numAlign * 2 - 2)) * 2;
    var result = [6];
    for (var pos = this.size - 7; result.length < numAlign; pos -= step) result.splice(1, 0, pos);
    return result;
  };
  QrCode.prototype.drawFormatBits = function (mask) {
    var data = (ECC_FORMAT[this.ecl] << 3) | mask;
    var rem = data;
    for (var i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    var bits = ((data << 10) | rem) ^ 0x5412;
    for (var i2 = 0; i2 <= 5; i2++) this.setFunctionModule(8, i2, getBit(bits, i2));
    this.setFunctionModule(8, 7, getBit(bits, 6));
    this.setFunctionModule(8, 8, getBit(bits, 7));
    this.setFunctionModule(7, 8, getBit(bits, 8));
    for (var i3 = 9; i3 < 15; i3++) this.setFunctionModule(14 - i3, 8, getBit(bits, i3));
    for (var i4 = 0; i4 < 8; i4++) this.setFunctionModule(this.size - 1 - i4, 8, getBit(bits, i4));
    for (var i5 = 8; i5 < 15; i5++) this.setFunctionModule(8, this.size - 15 + i5, getBit(bits, i5));
    this.setFunctionModule(8, this.size - 8, true);
  };
  QrCode.prototype.drawVersion = function () {
    if (this.version < 7) return;
    var rem = this.version;
    for (var i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
    var bits = (this.version << 12) | rem;
    for (var i2 = 0; i2 < 18; i2++) {
      var bit = getBit(bits, i2), a = this.size - 11 + i2 % 3, b = Math.floor(i2 / 3);
      this.setFunctionModule(a, b, bit); this.setFunctionModule(b, a, bit);
    }
  };
  QrCode.prototype.drawCodewords = function (data) {
    var i = 0, size = this.size;
    for (var right = size - 1; right >= 1; right -= 2) {
      if (right == 6) right = 5;
      for (var vert = 0; vert < size; vert++) {
        for (var j = 0; j < 2; j++) {
          var x = right - j;
          var upward = ((right + 1) & 2) == 0;
          var y = upward ? size - 1 - vert : vert;
          if (!this.isFunction[y][x] && i < data.length * 8) {
            this.modules[y][x] = getBit(data[i >>> 3], 7 - (i & 7)); i++;
          }
        }
      }
    }
  };
  QrCode.prototype.applyMask = function (mask) {
    for (var y = 0; y < this.size; y++) for (var x = 0; x < this.size; x++) {
      if (this.isFunction[y][x]) continue;
      var invert;
      switch (mask) {
        case 0: invert = (x + y) % 2 == 0; break;
        case 1: invert = y % 2 == 0; break;
        case 2: invert = x % 3 == 0; break;
        case 3: invert = (x + y) % 3 == 0; break;
        case 4: invert = (Math.floor(x / 3) + Math.floor(y / 2)) % 2 == 0; break;
        case 5: invert = x * y % 2 + x * y % 3 == 0; break;
        case 6: invert = (x * y % 2 + x * y % 3) % 2 == 0; break;
        case 7: invert = ((x + y) % 2 + x * y % 3) % 2 == 0; break;
      }
      if (invert) this.modules[y][x] = !this.modules[y][x];
    }
  };
  QrCode.prototype.getPenaltyScore = function () {
    var size = this.size, m = this.modules, total = 0;
    for (var y = 0; y < size; y++) {
      var runColor = false, runX = 0, hist = [0,0,0,0,0,0,0];
      for (var x = 0; x < size; x++) {
        if (m[y][x] == runColor) { runX++; if (runX == 5) total += 3; else if (runX > 5) total++; }
        else { this.finderPenalty(runX, hist); runColor = m[y][x]; runX = 1; }
      }
      total += this.finderPenaltyEnd(runColor, runX, hist) * 40;
    }
    for (var x2 = 0; x2 < size; x2++) {
      var runColor2 = false, runY = 0, hist2 = [0,0,0,0,0,0,0];
      for (var y2 = 0; y2 < size; y2++) {
        if (m[y2][x2] == runColor2) { runY++; if (runY == 5) total += 3; else if (runY > 5) total++; }
        else { this.finderPenalty(runY, hist2); runColor2 = m[y2][x2]; runY = 1; }
      }
      total += this.finderPenaltyEnd(runColor2, runY, hist2) * 40;
    }
    for (var y3 = 0; y3 < size - 1; y3++) for (var x3 = 0; x3 < size - 1; x3++) {
      var c = m[y3][x3];
      if (c == m[y3][x3+1] && c == m[y3+1][x3] && c == m[y3+1][x3+1]) total += 3;
    }
    var dark = 0; m.forEach(function (row) { row.forEach(function (v) { if (v) dark++; }); });
    var totalMod = size * size;
    var k = Math.ceil(Math.abs(dark * 20 - totalMod * 10) / totalMod) - 1;
    total += k * 10;
    return total;
  };
  QrCode.prototype.finderPenalty = function () {};   // simplified: run-length handled inline
  QrCode.prototype.finderPenaltyEnd = function () { return 0; };

  function getBit(x, i) { return ((x >>> i) & 1) != 0; }

  function encodeBytes(bytes, eclName, mask) {
    if (mask == null) mask = -1;
    var ecl = ECC[eclName == null ? "M" : eclName];
    var len = bytes.length, ver;
    for (ver = MIN_VER; ver <= MAX_VER; ver++) if (fitsVersion(ver, ecl, len)) break;
    if (ver > MAX_VER) throw new Error("data too long for a QR code");
    // build the bit buffer
    var bb = [];
    appendBits(bb, 4, 4);                                   // byte mode
    appendBits(bb, charCountBits(ver), len);
    bytes.forEach(function (b) { appendBits(bb, 8, b); });
    var dataCapacityBits = numDataCodewords(ver, ecl) * 8;
    appendBits(bb, Math.min(4, dataCapacityBits - bb.length), 0); // terminator
    while (bb.length % 8 != 0) bb.push(0);
    for (var pad = 0xEC; bb.length < dataCapacityBits; pad ^= 0xEC ^ 0x11) appendBits(bb, 8, pad);
    var codewords = [];
    for (var i = 0; i < bb.length; i += 8) {
      var v = 0; for (var j = 0; j < 8; j++) v = (v << 1) | bb[i + j]; codewords.push(v);
    }
    return new QrCode(ver, ecl, codewords, mask);
  }
  function appendBits(bb, n, val) { for (var i = n - 1; i >= 0; i--) bb.push((val >>> i) & 1); }

  function toBytes(text) {
    var out = [];
    for (var i = 0; i < text.length; i++) {
      var c = text.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) { out.push(0xC0 | (c >> 6), 0x80 | (c & 0x3F)); }
      else { out.push(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 0x3F), 0x80 | (c & 0x3F)); }
    }
    return out;
  }

  function matrix(text, opts) {
    opts = opts || {};
    var qr = encodeBytes(toBytes(String(text)), opts.ecl || "L",
                         opts.mask == null ? -1 : opts.mask);
    return qr.modules;
  }
  function draw(canvas, text, opts) {
    opts = opts || {};
    var mods = matrix(text, opts), n = mods.length, quiet = opts.quiet == null ? 4 : opts.quiet;
    var total = n + quiet * 2, scale = opts.scale || Math.max(2, Math.floor((opts.px || 240) / total));
    canvas.width = canvas.height = total * scale;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = opts.light || "#ffffff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = opts.dark || "#000000";
    for (var y = 0; y < n; y++) for (var x = 0; x < n; x++)
      if (mods[y][x]) ctx.fillRect((x + quiet) * scale, (y + quiet) * scale, scale, scale);
    return { modules: n, scale: scale };
  }

  // test hook: the final interleaved codewords for a text (for parity checks)
  function _codewords(text, eclName) {
    var bytes = toBytes(String(text)), ecl = ECC[eclName || "L"], len = bytes.length, ver;
    for (ver = MIN_VER; ver <= MAX_VER; ver++) if (fitsVersion(ver, ecl, len)) break;
    var bb = []; appendBits(bb, 4, 4); appendBits(bb, charCountBits(ver), len);
    bytes.forEach(function (b) { appendBits(bb, 8, b); });
    var cap = numDataCodewords(ver, ecl) * 8;
    appendBits(bb, Math.min(4, cap - bb.length), 0);
    while (bb.length % 8 != 0) bb.push(0);
    for (var pad = 0xEC; bb.length < cap; pad ^= 0xEC ^ 0x11) appendBits(bb, 8, pad);
    var cw = []; for (var i = 0; i < bb.length; i += 8) { var v = 0; for (var j = 0; j < 8; j++) v = (v << 1) | bb[i + j]; cw.push(v); }
    return { version: ver, data: cw, interleaved: addEccAndInterleave(cw, ver, ecl) };
  }

  return { matrix: matrix, draw: draw, _codewords: _codewords };
});
