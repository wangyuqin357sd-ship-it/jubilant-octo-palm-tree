/*!
 * docx-mini.js —— 零依赖的 .docx 生成器（单文件，浏览器 / Node 通用）
 * ============================================================================
 *
 * 公开 API（严格按约定实现，只此两项）：
 *
 *   DocxMini.buildBytes(paragraphs, opts) -> Promise<Uint8Array>
 *   DocxMini.build(paragraphs, opts)      -> Promise<Blob>
 *
 *   paragraphs: [{ text, style }]，style 支持 "title" | "heading" | "normal"（默认 normal）
 *   opts: { title, fontFamily, fontSize }   可选
 *
 * 参数细节：
 *   - text 支持 \n（段落内换行 -> <w:br/>）与 \t（制表 -> <w:tab/>），读回来仍是 \n / \t
 *   - paragraphs 也容忍直接给字符串（当 { text, style:"normal" } 处理）；
 *     null / undefined 元素当空段落处理
 *   - opts.title：非空时会被写成文档第 1 段的 Title 标题（若首段本来就是同名 title 则不重复添加），
 *     同时写入 docProps/core.xml 的 dc:title
 *   - opts.fontFamily：同时用于 ascii / hAnsi / eastAsia / cs 四个字体槽（中文靠 eastAsia 槽）
 *   - opts.fontSize：单位「磅」（pt），内部换算成 Word 的半磅 w:sz
 *   - 额外可选（都有默认值，不影响上面的约定）：
 *       compress?: boolean     是否尝试 deflate（默认 true；失败自动退回 stored）
 *       creator?: string       docProps/core.xml 的 dc:creator（默认 "yuyi-preview"）
 *       date?: Date|number     zip 内的时间戳（默认固定值，保证产物可复现）
 *
 * 产物结构（OPC 最小可用集）：
 *   [Content_Types].xml
 *   _rels/.rels
 *   docProps/core.xml
 *   docProps/app.xml
 *   word/document.xml
 *   word/_rels/document.xml.rels
 *   word/styles.xml
 *
 * ZIP 实现：优先用 CompressionStream('deflate-raw')（Chrome 103+ / Safari 16.4+ /
 * Firefox 113+ / Node 18+）；若该 API 不存在、压缩失败、或压完反而更大，则**逐条**退回
 * stored（method 0，完全不压缩）。也就是说：**没有 CompressionStream 也能正常出文件**，
 * 只是体积大一些。全程不用任何第三方库、不用 CDN。
 *
 * 文本编码：UTF-8（package 内 XML 声明 encoding="UTF-8"），中文 / emoji / 盲文点字都按原样写入。
 */
(function (globalScope) {
  "use strict";

  /* ------------------------------------------------------------------ 常量 */

  var MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  var CT_MAIN_DOCUMENT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml";
  var CT_STYLES = "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml";
  var CT_CORE_PROPS = "application/vnd.openxmlformats-package.core-properties+xml";
  var CT_APP_PROPS = "application/vnd.openxmlformats-officedocument.extended-properties+xml";
  var REL_CORE_PROPS = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties";
  var DEFAULT_FONT = "Microsoft YaHei";
  var DEFAULT_FONT_SIZE_PT = 10.5;
  var DEFAULT_CREATOR = "yuyi-preview";
  // 固定时间戳（UTC），让同样的输入产出同样的字节，便于测试与比对
  var DEFAULT_DATE = Date.UTC(2020, 0, 1, 0, 0, 0);

  var NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
  var NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
  var NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types";
  var NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships";
  var NS_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties";
  var NS_DC = "http://purl.org/dc/elements/1.1/";
  var NS_DCTERMS = "http://purl.org/dc/terms/";
  var NS_DCMITYPE = "http://purl.org/dc/dcmitype/";
  var NS_XSI = "http://www.w3.org/2001/XMLSchema-instance";
  var NS_EP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties";
  var NS_VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes";

  var XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n';

  /* -------------------------------------------------------------- 文本工具 */

  var HAS_TEXT_ENCODER = (typeof TextEncoder !== "undefined");

  function utf8EncodeManual(str) {
    var out = [];
    for (var i = 0; i < str.length; i++) {
      var cp = str.charCodeAt(i);
      // 组合代理对（surrogate pair）成一个码点
      if (cp >= 0xd800 && cp <= 0xdbff && i + 1 < str.length) {
        var lo = str.charCodeAt(i + 1);
        if (lo >= 0xdc00 && lo <= 0xdfff) {
          cp = ((cp - 0xd800) << 10) + (lo - 0xdc00) + 0x10000;
          i++;
        }
      }
      if (cp < 0x80) {
        out.push(cp);
      } else if (cp < 0x800) {
        out.push(0xc0 | (cp >> 6), 0x80 | (cp & 0x3f));
      } else if (cp < 0x10000) {
        out.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
      } else {
        out.push(
          0xf0 | (cp >> 18),
          0x80 | ((cp >> 12) & 0x3f),
          0x80 | ((cp >> 6) & 0x3f),
          0x80 | (cp & 0x3f)
        );
      }
    }
    return new Uint8Array(out);
  }

  function utf8Encode(str) {
    if (HAS_TEXT_ENCODER) return new TextEncoder().encode(str);
    return utf8EncodeManual(str);
  }

  var XML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" };

  // 去掉 XML 1.0 里非法的控制字符（保留 \t \n \r），再转义 & < > " '
  function escapeXml(value) {
    var s = String(value == null ? "" : value);
    s = s.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]/g, "");
    return s.replace(/[&<>"']/g, function (ch) {
      return XML_ESCAPES[ch];
    });
  }

  function concatBytes(list) {
    var total = 0;
    var i;
    for (i = 0; i < list.length; i++) total += list[i].length;
    var out = new Uint8Array(total);
    var pos = 0;
    for (i = 0; i < list.length; i++) {
      out.set(list[i], pos);
      pos += list[i].length;
    }
    return out;
  }

  /* ------------------------------------------------------------------ CRC32 */

  var CRC_TABLE = null;

  function crcTable() {
    if (CRC_TABLE) return CRC_TABLE;
    var t = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    CRC_TABLE = t;
    return t;
  }

  function crc32(bytes) {
    var t = crcTable();
    var c = 0xffffffff;
    for (var i = 0; i < bytes.length; i++) c = t[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  /* -------------------------------------------------------------- deflate */

  var HAS_COMPRESSION_STREAM = typeof CompressionStream !== "undefined";
  var HAS_BLOB = typeof Blob !== "undefined";
  var HAS_RESPONSE = typeof Response !== "undefined";

  // 返回 deflate-raw 后的字节；任何情况下失败都返回 null（调用方退回 stored）
  function deflateRaw(bytes) {
    return new Promise(function (resolve) {
      if (!HAS_COMPRESSION_STREAM || !HAS_BLOB || !HAS_RESPONSE) return resolve(null);
      try {
        var stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate-raw"));
        new Response(stream)
          .arrayBuffer()
          .then(function (buf) {
            resolve(new Uint8Array(buf));
          })
          .catch(function () {
            resolve(null);
          });
      } catch (e) {
        resolve(null);
      }
    });
  }

  /* ------------------------------------------------------------------- ZIP */

  function dosDateTime(date) {
    var y = date.getUTCFullYear();
    if (y < 1980) y = 1980;
    var d = ((y - 1980) << 9) | ((date.getUTCMonth() + 1) << 5) | date.getUTCDate();
    var t = (date.getUTCHours() << 11) | (date.getUTCMinutes() << 5) | (date.getUTCSeconds() >> 1);
    return { date: d & 0xffff, time: t & 0xffff };
  }

  // entries: [{ name: string, data: Uint8Array }]
  function makeZip(entries, opts) {
    var dt = dosDateTime(opts.date);
    var flag = 0x0800; // bit 11：文件名按 UTF-8 解释
    var chunks = [];
    var central = [];
    var offset = 0;
    var i;

    function localHeader(nameBytes, method, crc, csize, usize) {
      var h = new Uint8Array(30 + nameBytes.length);
      var v = new DataView(h.buffer);
      v.setUint32(0, 0x04034b50, true);
      v.setUint16(4, 20, true); // version needed to extract 2.0
      v.setUint16(6, flag, true);
      v.setUint16(8, method, true);
      v.setUint16(10, dt.time, true);
      v.setUint16(12, dt.date, true);
      v.setUint32(14, crc, true);
      v.setUint32(18, csize, true);
      v.setUint32(22, usize, true);
      v.setUint16(26, nameBytes.length, true);
      v.setUint16(28, 0, true); // extra field length
      h.set(nameBytes, 30);
      return h;
    }

    var chain = Promise.resolve();

    entries.forEach(function (entry) {
      chain = chain.then(function () {
        var nameBytes = utf8Encode(entry.name);
        var raw = entry.data;
        var crc = crc32(raw);
        var finish = function (method, payload) {
          var lh = localHeader(nameBytes, method, crc, payload.length, raw.length);
          chunks.push(lh, payload);
          central.push({
            nameBytes: nameBytes,
            method: method,
            crc: crc,
            csize: payload.length,
            usize: raw.length,
            offset: offset
          });
          offset += lh.length + payload.length;
        };
        if (!opts.compress) return finish(0, raw);
        return deflateRaw(raw).then(function (packed) {
          if (packed && packed.length < raw.length) finish(8, packed);
          else finish(0, raw); // stored 兜底
        });
      });
    });

    return chain.then(function () {
      var cdChunks = [];
      var cdSize = 0;
      central.forEach(function (c) {
        var h = new Uint8Array(46 + c.nameBytes.length);
        var v = new DataView(h.buffer);
        v.setUint32(0, 0x02014b50, true);
        v.setUint16(4, 20, true); // version made by (MS-DOS, 2.0)
        v.setUint16(6, 20, true); // version needed
        v.setUint16(8, flag, true);
        v.setUint16(10, c.method, true);
        v.setUint16(12, dt.time, true);
        v.setUint16(14, dt.date, true);
        v.setUint32(16, c.crc, true);
        v.setUint32(20, c.csize, true);
        v.setUint32(24, c.usize, true);
        v.setUint16(28, c.nameBytes.length, true);
        v.setUint16(30, 0, true); // extra
        v.setUint16(32, 0, true); // comment
        v.setUint16(34, 0, true); // disk number start
        v.setUint16(36, 0, true); // internal attrs
        v.setUint32(38, 0, true); // external attrs
        v.setUint32(42, c.offset, true);
        h.set(c.nameBytes, 46);
        cdChunks.push(h);
        cdSize += h.length;
      });

      var eocd = new Uint8Array(22);
      var ev = new DataView(eocd.buffer);
      ev.setUint32(0, 0x06054b50, true);
      ev.setUint16(4, 0, true); // this disk
      ev.setUint16(6, 0, true); // disk with central dir
      ev.setUint16(8, central.length, true);
      ev.setUint16(10, central.length, true);
      ev.setUint32(12, cdSize, true);
      ev.setUint32(16, offset, true);
      ev.setUint16(20, 0, true); // comment length

      return concatBytes(chunks.concat(cdChunks).concat([eocd]));
    });
  }

  /* ---------------------------------------------------------------- 输入整理 */

  function styleIdOf(style) {
    var s = String(style == null ? "" : style).trim().toLowerCase();
    if (s === "title") return "Title";
    if (s === "heading" || s === "heading1" || s === "h1") return "Heading1";
    if (s === "heading2" || s === "h2") return "Heading2";
    if (s === "heading3" || s === "h3") return "Heading3";
    if (s === "normal" || s === "") return "Normal";
    return "Normal"; // 未知样式一律当正文，绝不因为样式名不认识就丢内容
  }

  function normalizeParagraphs(paragraphs, opts) {
    if (paragraphs == null) paragraphs = [];
    if (typeof paragraphs === "string") paragraphs = [paragraphs];
    if (!Array.isArray(paragraphs)) {
      throw new TypeError("DocxMini: paragraphs 必须是数组，收到 " + typeof paragraphs);
    }
    var out = [];
    for (var i = 0; i < paragraphs.length; i++) {
      var item = paragraphs[i];
      if (item == null) {
        out.push({ text: "", style: "normal" });
      } else if (typeof item === "object") {
        out.push({
          text: item.text == null ? "" : String(item.text),
          style: item.style == null ? "normal" : String(item.style)
        });
      } else {
        out.push({ text: String(item), style: "normal" });
      }
    }
    var title = opts.title;
    if (title) {
      var head = out[0];
      var dup = head && styleIdOf(head.style) === "Title" && head.text === title;
      if (!dup) out.unshift({ text: title, style: "title" });
    }
    return out;
  }

  function normalizeOpts(opts) {
    opts = opts || {};
    var font = opts.fontFamily == null ? "" : String(opts.fontFamily).trim();
    if (!font) font = DEFAULT_FONT;
    var pt = opts.fontSize == null ? DEFAULT_FONT_SIZE_PT : Number(opts.fontSize);
    if (!isFinite(pt) || pt <= 0) pt = DEFAULT_FONT_SIZE_PT;
    var halfPt = Math.round(pt * 2);
    if (halfPt < 2) halfPt = 2;
    if (halfPt > 1638) halfPt = 1638;

    var date;
    if (opts.date == null) date = new Date(DEFAULT_DATE);
    else if (opts.date instanceof Date) date = opts.date;
    else date = new Date(Number(opts.date));
    if (isNaN(date.getTime())) date = new Date(DEFAULT_DATE);

    return {
      title: opts.title == null ? "" : String(opts.title),
      fontFamily: font,
      halfPt: halfPt,
      compress: opts.compress !== false,
      creator: opts.creator == null || String(opts.creator) === "" ? DEFAULT_CREATOR : String(opts.creator),
      date: date
    };
  }

  /* ------------------------------------------------------------- OOXML 部件 */

  function contentTypesXml() {
    return (
      XML_DECL +
      '<Types xmlns="' + NS_CT + '">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/word/document.xml" ContentType="' + CT_MAIN_DOCUMENT + '"/>' +
      '<Override PartName="/word/styles.xml" ContentType="' + CT_STYLES + '"/>' +
      '<Override PartName="/docProps/core.xml" ContentType="' + CT_CORE_PROPS + '"/>' +
      '<Override PartName="/docProps/app.xml" ContentType="' + CT_APP_PROPS + '"/>' +
      "</Types>"
    );
  }

  function rootRelsXml() {
    return (
      XML_DECL +
      '<Relationships xmlns="' + NS_REL + '">' +
      '<Relationship Id="rId1" Type="' + NS_R + '/officeDocument" Target="word/document.xml"/>' +
      '<Relationship Id="rId2" Type="' + REL_CORE_PROPS + '" Target="docProps/core.xml"/>' +
      '<Relationship Id="rId3" Type="' + NS_R + '/extended-properties" Target="docProps/app.xml"/>' +
      "</Relationships>"
    );
  }

  function documentRelsXml() {
    return (
      XML_DECL +
      '<Relationships xmlns="' + NS_REL + '">' +
      '<Relationship Id="rId1" Type="' + NS_R + '/styles" Target="styles.xml"/>' +
      "</Relationships>"
    );
  }

  // 一段文字 -> 一个 <w:r>（内部用 <w:br/> / <w:tab/> / <w:t> 表达换行与制表）
  function runXml(text) {
    var parts = [];
    var lines = String(text).split(/\r\n|\r|\n/);
    for (var i = 0; i < lines.length; i++) {
      if (i > 0) parts.push("<w:br/>");
      var segs = lines[i].split("\t");
      for (var j = 0; j < segs.length; j++) {
        if (j > 0) parts.push("<w:tab/>");
        if (segs[j] !== "") parts.push('<w:t xml:space="preserve">' + escapeXml(segs[j]) + "</w:t>");
      }
    }
    if (!parts.length) return "";
    return "<w:r>" + parts.join("") + "</w:r>";
  }

  function paragraphXml(p) {
    return '<w:p><w:pPr><w:pStyle w:val="' + styleIdOf(p.style) + '"/></w:pPr>' + runXml(p.text) + "</w:p>";
  }

  function documentXml(paragraphs, o) {
    var body = "";
    for (var i = 0; i < paragraphs.length; i++) body += paragraphXml(paragraphs[i]);
    // 正文区段属性：A4 纵向 + 常规页边距
    body +=
      "<w:sectPr>" +
      '<w:pgSz w:w="11906" w:h="16838"/>' +
      '<w:pgMar w:top="1440" w:right="1418" w:bottom="1440" w:left="1418" w:header="851" w:footer="992" w:gutter="0"/>' +
      '<w:cols w:space="425"/>' +
      '<w:docGrid w:type="lines" w:linePitch="312"/>' +
      "</w:sectPr>";
    return (
      XML_DECL +
      '<w:document xmlns:w="' + NS_W + '" xmlns:r="' + NS_R + '">' +
      "<w:body>" + body + "</w:body>" +
      "</w:document>"
    );
  }

  function stylesXml(o) {
    var f = escapeXml(o.fontFamily);
    var sz = o.halfPt;
    var fonts =
      '<w:rFonts w:ascii="' + f + '" w:hAnsi="' + f + '" w:eastAsia="' + f + '" w:cs="' + f + '"/>';
    var lang = '<w:lang w:val="en-US" w:eastAsia="zh-CN" w:bidi="ar-SA"/>';

    function heading(id, name, halfSize, level) {
      return (
        '<w:style w:type="paragraph" w:styleId="' + id + '"><w:name w:val="' + name + '"/>' +
        '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>' +
        "<w:pPr><w:keepNext/><w:spacing w:before=\"240\" w:after=\"120\"/>" +
        '<w:outlineLvl w:val="' + level + '"/></w:pPr>' +
        "<w:rPr>" + fonts + "<w:b/>" +
        '<w:sz w:val="' + halfSize + '"/><w:szCs w:val="' + halfSize + '"/>' + lang + "</w:rPr></w:style>"
      );
    }

    return (
      XML_DECL +
      '<w:styles xmlns:w="' + NS_W + '">' +
      "<w:docDefaults>" +
      "<w:rPrDefault><w:rPr>" + fonts +
      '<w:sz w:val="' + sz + '"/><w:szCs w:val="' + sz + '"/>' + lang + "</w:rPr></w:rPrDefault>" +
      '<w:pPrDefault><w:pPr><w:widowControl w:val="0"/></w:pPr></w:pPrDefault>' +
      "</w:docDefaults>" +
      '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>' +
      "<w:rPr>" + fonts + '<w:sz w:val="' + sz + '"/><w:szCs w:val="' + sz + '"/>' + lang + "</w:rPr></w:style>" +
      '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>' +
      '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>' +
      '<w:pPr><w:spacing w:before="240" w:after="120"/><w:jc w:val="center"/></w:pPr>' +
      "<w:rPr>" + fonts + "<w:b/>" + '<w:sz w:val="44"/><w:szCs w:val="44"/>' + lang + "</w:rPr></w:style>" +
      heading("Heading1", "heading 1", 32, 0) +
      heading("Heading2", "heading 2", 28, 1) +
      heading("Heading3", "heading 3", 24, 2) +
      "</w:styles>"
    );
  }

  function w3cdtf(date) {
    return date.toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  function coreXml(o) {
    var stamp = w3cdtf(o.date);
    return (
      XML_DECL +
      '<cp:coreProperties xmlns:cp="' + NS_CP + '" xmlns:dc="' + NS_DC + '" xmlns:dcterms="' + NS_DCTERMS +
      '" xmlns:dcmitype="' + NS_DCMITYPE + '" xmlns:xsi="' + NS_XSI + '">' +
      "<dc:title>" + escapeXml(o.title) + "</dc:title>" +
      "<dc:creator>" + escapeXml(o.creator) + "</dc:creator>" +
      "<cp:lastModifiedBy>" + escapeXml(o.creator) + "</cp:lastModifiedBy>" +
      '<dcterms:created xsi:type="dcterms:W3CDTF">' + stamp + "</dcterms:created>" +
      '<dcterms:modified xsi:type="dcterms:W3CDTF">' + stamp + "</dcterms:modified>" +
      "</cp:coreProperties>"
    );
  }

  function appXml() {
    return (
      XML_DECL +
      '<Properties xmlns="' + NS_EP + '" xmlns:vt="' + NS_VT + '">' +
      "<Application>DocxMini</Application>" +
      "<DocSecurity>0</DocSecurity>" +
      "<ScaleCrop>false</ScaleCrop>" +
      "<LinksUpToDate>false</LinksUpToDate>" +
      "<SharedDoc>false</SharedDoc>" +
      "<HyperlinksChanged>false</HyperlinksChanged>" +
      "<AppVersion>1.0000</AppVersion>" +
      "</Properties>"
    );
  }

  function buildParts(paragraphs, o) {
    var xml = [
      ["[Content_Types].xml", contentTypesXml()],
      ["_rels/.rels", rootRelsXml()],
      ["docProps/core.xml", coreXml(o)],
      ["docProps/app.xml", appXml()],
      ["word/document.xml", documentXml(paragraphs, o)],
      ["word/_rels/document.xml.rels", documentRelsXml()],
      ["word/styles.xml", stylesXml(o)]
    ];
    return xml.map(function (pair) {
      return { name: pair[0], data: utf8Encode(pair[1]) };
    });
  }

  /* --------------------------------------------------------------- 对外 API */

  function buildBytes(paragraphs, opts) {
    var o, list, entries;
    try {
      o = normalizeOpts(opts);
      list = normalizeParagraphs(paragraphs, o);
      entries = buildParts(list, o);
    } catch (e) {
      return Promise.reject(e);
    }
    return makeZip(entries, o);
  }

  function build(paragraphs, opts) {
    return buildBytes(paragraphs, opts).then(function (bytes) {
      if (typeof Blob === "undefined") {
        throw new Error("DocxMini: 当前环境没有 Blob，请改用 buildBytes()");
      }
      return new Blob([bytes], { type: MIME });
    });
  }

  var DocxMini = { build: build, buildBytes: buildBytes };

  if (typeof module !== "undefined" && module && module.exports) module.exports = DocxMini;
  if (globalScope) {
    try {
      globalScope.DocxMini = DocxMini;
    } catch (e) {
      /* 忽略只读全局对象 */
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : typeof self !== "undefined" ? self : this);