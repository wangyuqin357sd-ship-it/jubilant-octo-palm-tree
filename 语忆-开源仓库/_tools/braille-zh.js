/*!
 * braille-zh.js — 中文 → 现行盲文（汉语盲文）浏览器引擎（零依赖，UMD）
 * ============================================================================
 *
 * 这是 `ai-voice-summary/scripts/braille_zh.py` 的浏览器端移植，目标是**逐字符等价**：
 * 同一份表数据、同一套查表顺序、同一套数字号 / 大写符 / 全角归一化规则。
 *
 * 表数据：`data/braille-zh.json`（与后端 `ai-voice-summary/data/braille_zh.json`
 * 语义等价：顶层 6 个键与映射值逐一相同，仅去掉缩进并在 meta 里补了来源与生成时间）。
 * 本文件不内置任何盲文点位，全部来自运行时加载的表。
 *
 * 用法：
 *   <script src="_tools/braille-zh.js"></script>
 *   <script>
 *     BrailleZH.load('data/braille-zh.json').then(function () {
 *       BrailleZH.toBrailleText('中国 2026 年');   // '⠌⠲⠛⠕ ⠼⠃⠚⠃⠋⠝⠩'
 *       BrailleZH.wrapCells(cells, 32);
 *       BrailleZH.cellsToUnicode('3456-245');      // '⠼⠚'
 *       BrailleZH.coverage('生僻字𠀋');             // ['𠀋']
 *     });
 *   </script>
 *
 * 与 Python 原实现的一致性要点（都做过逐字符比对，见 verify-braille-parity.py）：
 *   * 内部一律按 **Unicode 码点**遍历/计数/切片，对应 Python 的 `str` 索引与 `len()`。
 *     JS 原生 `.length` 是 UTF-16 码元数，遇到 emoji / CJK 扩展 B 会与 Python 不一致，
 *     所以本文件不用它来算方数和折行。
 *   * 未覆盖字符原样保留（与 Python 相同），因此盲文串里可能出现非 BMP 字符。
 *   * `stats().unmapped_chars` 的排序按码点比较，对应 Python 的 `sorted(set(...))`。
 *   * 折行时 `current.strip()` 用 Python 的空白定义（含 U+001C–U+001F、U+0085、
 *     U+00A0、U+1680、U+2000–U+200A、U+2028/9、U+202F、U+205F、U+3000），
 *     不是 JS 的 `trim()`。
 *
 * 有意保留的差异（仅在非法入参时出现，正常调用看不到）：
 *   * Python 的 `ValueError` → JS 的 `RangeError`；`TypeError` 保持 `TypeError`。
 *   * `wrapCells` 对非字符串的 braille 入参抛 `TypeError`（Python 会抛 AttributeError）。
 *
 * 未移植的逻辑见文件末尾「未移植 / 已知边界」注释。
 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(typeof require === 'function' ? require : null);
  } else if (typeof define === 'function' && define.amd) {
    define([], function () { return factory(null); });
  } else {
    root.BrailleZH = factory(null);
  }
})(typeof globalThis !== 'undefined' ? globalThis
  : (typeof self !== 'undefined' ? self : this), function (nodeRequire) {
  'use strict';

  /* ---------------------------------------------------------------- 常量 */

  var NUMBER_SIGN = '\u283C';    // ⠼ 数符
  var CAPITAL_SIGN = '\u2820';   // ⠠ 大写符
  var BLANK_CELL = '\u2800';     // 空方
  var DEFAULT_WIDTH = 32;        // 与后端 wrap_cells(width=32) / BRF 约定一致
  var DEFAULT_DATA_URL = 'data/braille-zh.json';

  /* ------------------------------------------------- 码点级字符串工具 */

  /**
   * 按 Unicode 码点切分，等价于 Python 对 `str` 的逐字符迭代。
   * （不成对的代理项各自算一个码点，与 Python 的 len() 行为一致。）
   */
  function toCodePoints(str) {
    var out = [];
    var i = 0;
    var n = str.length;
    while (i < n) {
      var hi = str.charCodeAt(i);
      if (hi >= 0xD800 && hi <= 0xDBFF && i + 1 < n) {
        var lo = str.charCodeAt(i + 1);
        if (lo >= 0xDC00 && lo <= 0xDFFF) {
          out.push(str.slice(i, i + 2));
          i += 2;
          continue;
        }
      }
      out.push(str.charAt(i));
      i += 1;
    }
    return out;
  }

  /** 等价于 Python 的 `len(str)`（码点数，不是 UTF-16 码元数）。 */
  function cpLength(str) {
    var n = 0;
    var i = 0;
    var len = str.length;
    while (i < len) {
      var hi = str.charCodeAt(i);
      if (hi >= 0xD800 && hi <= 0xDBFF && i + 1 < len) {
        var lo = str.charCodeAt(i + 1);
        if (lo >= 0xDC00 && lo <= 0xDFFF) { i += 2; n += 1; continue; }
      }
      i += 1;
      n += 1;
    }
    return n;
  }

  /** Python 的 `str.isspace()`（不是 JS 的 `\s`）。 */
  function isPySpace(ch) {
    var c = ch.codePointAt(0);
    if (c === 0x20) { return true; }
    if (c >= 0x09 && c <= 0x0D) { return true; }
    if (c >= 0x1C && c <= 0x1F) { return true; }
    if (c === 0x85 || c === 0xA0 || c === 0x1680) { return true; }
    if (c >= 0x2000 && c <= 0x200A) { return true; }
    if (c === 0x2028 || c === 0x2029 || c === 0x202F || c === 0x205F) { return true; }
    return c === 0x3000;
  }

  /** 等价于 Python 的 `str.strip()`（无参数版）。 */
  function pyStrip(str) {
    var cps = toCodePoints(str);
    var i = 0;
    var j = cps.length;
    while (i < j && isPySpace(cps[i])) { i += 1; }
    while (j > i && isPySpace(cps[j - 1])) { j -= 1; }
    return cps.slice(i, j).join('');
  }

  /** 按码点比较两个字符串，等价于 Python 的字符串 `<` / `sorted()`。 */
  function pyCompare(a, b) {
    var ca = toCodePoints(a);
    var cb = toCodePoints(b);
    var n = ca.length < cb.length ? ca.length : cb.length;
    for (var i = 0; i < n; i += 1) {
      var va = ca[i].codePointAt(0);
      var vb = cb[i].codePointAt(0);
      if (va !== vb) { return va < vb ? -1 : 1; }
    }
    if (ca.length === cb.length) { return 0; }
    return ca.length < cb.length ? -1 : 1;
  }

  function hasOwn(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
  }

  /* ----------------------------------------------------- 全角归一化表 */

  var FULLWIDTH_DIGITS = {};
  var FULLWIDTH_LOWER = {};
  var FULLWIDTH_UPPER = {};
  (function buildFullwidth() {
    var i;
    for (i = 0; i < 10; i += 1) {
      FULLWIDTH_DIGITS[String.fromCharCode(0xFF10 + i)] = String(i);
    }
    for (i = 0; i < 26; i += 1) {
      FULLWIDTH_LOWER[String.fromCharCode(0xFF41 + i)] = String.fromCharCode(97 + i);
      FULLWIDTH_UPPER[String.fromCharCode(0xFF21 + i)] = String.fromCharCode(65 + i);
    }
  }());

  function normalizeFullwidth(map, ch) {
    return hasOwn(map, ch) ? map[ch] : ch;
  }

  /**
   * 对应 Python `normalized.isdigit()`。
   * 表里 `digits` 的键固定是 10 个 ASCII 数字（`install()` 会校验），
   * 所以「ASCII 数字」与 Python 的 `isdigit() and normalized in digits` 等价。
   */
  function isDigit(ch) {
    return ch.length === 1 && ch >= '0' && ch <= '9';
  }

  /* ------------------------------------------------------- 表数据与状态 */

  var state = { table: null, meta: {} };
  var loadPromises = {};

  /** 等价于 Python 的 `cells_to_unicode()`：'3-256' → '⠌⠲'；'0' → U+2800。 */
  function cellsToUnicode(spec) {
    if (typeof spec !== 'string') {
      throw new TypeError('点位写法必须是字符串，收到 ' + typeof spec);
    }
    var groups = spec.split('-');
    var out = [];
    for (var g = 0; g < groups.length; g += 1) {
      var group = groups[g];
      var value = 0;
      for (var i = 0; i < group.length; i += 1) {
        var digit = group.charAt(i);
        var code = digit.charCodeAt(0);
        if (digit.length !== 1 || code < 48 || code > 57) {
          // Python 的 int(digit) 在这里抛 ValueError
          throw new Error('非法点位写法：' + JSON.stringify(spec));
        }
        var index = code - 48;
        if (index === 0) { continue; }
        if (index >= 1 && index <= 8) { value |= 1 << (index - 1); }
      }
      out.push(String.fromCharCode(0x2800 + value));
    }
    return out.join('');
  }

  function stripPrefix(str, prefix) {
    return str.indexOf(prefix) === 0 ? str.slice(prefix.length) : str;
  }

  function mapSpecs(obj, fn) {
    var out = {};
    for (var key in obj) {
      if (hasOwn(obj, key)) { out[key] = fn(obj[key]); }
    }
    return out;
  }

  /**
   * 装载已解析的表对象（对应 Python `_load_table()` 的派生逻辑）。
   * 浏览器里通常不直接调用，用 `load()` 即可。
   */
  function install(raw) {
    if (!raw || typeof raw !== 'object') {
      throw new TypeError('盲文表数据必须是一个对象');
    }
    var required = ['chars', 'digits', 'lower', 'upper', 'words'];
    for (var i = 0; i < required.length; i += 1) {
      var name = required[i];
      if (!raw[name] || typeof raw[name] !== 'object') {
        throw new Error('盲文表缺少字段：' + name);
      }
    }
    // 与 Python 的 `normalized.isdigit() and normalized in digits` 等价的前提
    var digitKeys = Object.keys(raw.digits);
    for (var d = 0; d < digitKeys.length; d += 1) {
      if (!isDigit(digitKeys[d])) {
        throw new Error(
          'digits 表出现了非 ASCII 数字键 ' + JSON.stringify(digitKeys[d]) +
          '，本移植的 isdigit 判定需要同步扩展，拒绝静默产生偏差');
      }
    }

    var digitsFull = mapSpecs(raw.digits, cellsToUnicode);
    // 上游表把数符写进了每个数字点位（'3456-245'），
    // 「一串数字只标一个数符」是盲文惯例，所以另存一份去掉数符的裸点位。
    var digitsBare = mapSpecs(digitsFull, function (v) { return stripPrefix(v, NUMBER_SIGN); });

    state.table = {
      meta: raw.meta || {},
      chars: mapSpecs(raw.chars, cellsToUnicode),
      words: mapSpecs(raw.words, cellsToUnicode),
      digits: digitsFull,
      digits_bare: digitsBare,
      lower: mapSpecs(raw.lower, cellsToUnicode),
      // 上游大写规则本身已含大写符（'6-1' → ⠠⠁），存裸点位，用的时候再加
      upper: mapSpecs(raw.upper, function (v) {
        return stripPrefix(cellsToUnicode(v), CAPITAL_SIGN);
      })
    };
    state.meta = state.table.meta;
    return state.table;
  }

  function requireTable() {
    if (!state.table) {
      throw new Error('盲文表尚未加载，请先 await BrailleZH.load("' + DEFAULT_DATA_URL + '")');
    }
    return state.table;
  }

  /* --------------------------------------------------------- 数据加载 */

  function isRemoteUrl(url) {
    return /^(https?:|data:|blob:)/i.test(url);
  }

  function fetchJson(url) {
    if (!isRemoteUrl(url) && nodeRequire) {
      // Node 环境下读本地文件（浏览器不会走到这里）
      return new Promise(function (resolve, reject) {
        nodeRequire('fs').readFile(url, 'utf8', function (err, text) {
          if (err) { reject(err); return; }
          try {
            resolve(JSON.parse(text));
          } catch (parseErr) {
            reject(parseErr);
          }
        });
      });
    }
    if (typeof fetch !== 'function') {
      return Promise.reject(new Error('当前环境没有 fetch，无法加载 ' + url));
    }
    return fetch(url, { credentials: 'same-origin' }).then(function (response) {
      if (!response.ok) {
        throw new Error('加载盲文表失败：HTTP ' + response.status + ' ' + url);
      }
      return response.json();
    });
  }

  /**
   * 加载并缓存盲文表。
   * @param {string|object} [url] 表地址；省略时用 'data/braille-zh.json'。
   *   直接传已解析的对象也可（等价于 `install()`）。
   * @returns {Promise<object>} 派生后的表
   */
  function load(url) {
    var key = (url === undefined || url === null) ? DEFAULT_DATA_URL : url;
    if (typeof key === 'object') {
      return Promise.resolve().then(function () { return install(key); });
    }
    key = String(key);
    if (hasOwn(loadPromises, key)) { return loadPromises[key]; }
    var promise = fetchJson(key).then(function (raw) {
      install(raw);
      return state.table;
    });
    loadPromises[key] = promise;
    // 失败不缓存，允许重试
    promise.catch(function () { delete loadPromises[key]; });
    return promise;
  }

  /** 表是否已就绪。 */
  function ready() {
    return state.table !== null;
  }

  /** 表元信息（对应 Python `table_info()`）。 */
  function tableInfo() {
    var out = {};
    for (var key in state.meta) {
      if (hasOwn(state.meta, key)) { out[key] = state.meta[key]; }
    }
    return out;
  }

  /* ----------------------------------------------------------- 核心遍历 */

  function readNumberSign(opts) {
    if (opts === undefined || opts === null) { return 'run'; }
    if (typeof opts === 'string') { return opts; }
    if (typeof opts === 'object' && opts.number_sign !== undefined) {
      return String(opts.number_sign);
    }
    return 'run';
  }

  /**
   * 逐个「源片段」产出 (源文本, 盲文, 是否命中)，
   * 查表顺序与 Python `_iter_cells()` 完全一致。
   */
  function eachCell(text, numberSign, visit) {
    var table = requireTable();
    var chars = table.chars;
    var words = table.words;
    var digits = table.digits;
    var digitsBare = table.digits_bare;
    var lower = table.lower;
    var upper = table.upper;

    var cp = toCodePoints(text);
    var index = 0;
    var length = cp.length;
    while (index < length) {
      var ch = cp[index];

      // 空白与换行：保持可读的排版，不写成空方
      if (ch === '\n') {
        visit('\n', '\n', true);
        index += 1;
        continue;
      }
      if (ch === ' ' || ch === '\t' || ch === '\u3000') {
        visit(ch, ' ', true);
        index += 1;
        continue;
      }

      // 1) 二字词规则优先（用于消解多音字）
      if (index + 1 < length) {
        var pair = ch + cp[index + 1];
        if (hasOwn(words, pair)) {
          visit(pair, words[pair], true);
          index += 2;
          continue;
        }
      }

      // 2) 单字 / 单符号
      if (hasOwn(chars, ch)) {
        visit(ch, chars[ch], true);
        index += 1;
        continue;
      }

      // 3) 数字（半角与全角）
      var normalized = normalizeFullwidth(FULLWIDTH_DIGITS, ch);
      if (isDigit(normalized) && hasOwn(digits, normalized)) {
        if (numberSign === 'run') {
          var srcRun = [];
          var cellsRun = [];
          while (index < length) {
            var candidate = normalizeFullwidth(FULLWIDTH_DIGITS, cp[index]);
            if (!isDigit(candidate) || !hasOwn(digits, candidate)) { break; }
            srcRun.push(cp[index]);
            cellsRun.push(digitsBare[candidate]);
            index += 1;
          }
          visit(srcRun.join(''), NUMBER_SIGN + cellsRun.join(''), true);
          continue;
        }
        visit(ch, digits[normalized], true);
        index += 1;
        continue;
      }

      // 4) 拉丁字母
      normalized = normalizeFullwidth(FULLWIDTH_LOWER, ch);
      if (hasOwn(lower, normalized)) {
        visit(ch, lower[normalized], true);
        index += 1;
        continue;
      }
      normalized = normalizeFullwidth(FULLWIDTH_UPPER, ch);
      if (hasOwn(upper, normalized)) {
        visit(ch, CAPITAL_SIGN + upper[normalized], true);
        index += 1;
        continue;
      }

      // 5) 未覆盖：原样保留并记录
      visit(ch, ch, false);
      index += 1;
    }
  }

  /* ------------------------------------------------------------ 转换 API */

  function makeResult(braille, source, unmapped, total, mapped) {
    var cps = toCodePoints(braille);
    var cellCount = 0;
    for (var i = 0; i < cps.length; i += 1) {
      if (cps[i] !== '\n') { cellCount += 1; }
    }
    var coverage = total <= 0 ? 1.0 : mapped / total;
    var result = {
      braille: braille,
      source: source,
      unmapped: unmapped,
      total_chars: total,
      mapped_chars: mapped,
      cell_count: cellCount,
      coverage: coverage
    };
    result.stats = function stats() {
      var seen = {};
      var unique = [];
      for (var j = 0; j < unmapped.length; j += 1) {
        if (!hasOwn(seen, unmapped[j])) {
          seen[unmapped[j]] = true;
          unique.push(unmapped[j]);
        }
      }
      unique.sort(pyCompare);
      return {
        total_chars: total,
        mapped_chars: mapped,
        unmapped_chars: unique,
        coverage: pyRound(coverage, 4),
        cell_count: cellCount,
        lines: countChar(braille, '\n') + 1
      };
    };
    return result;
  }

  function countChar(str, target) {
    var cps = toCodePoints(str);
    var n = 0;
    for (var i = 0; i < cps.length; i += 1) {
      if (cps[i] === target) { n += 1; }
    }
    return n;
  }

  /**
   * 等价于 Python `round(x, 4)`。
   * 4 位小数的「平局」在 IEEE-754 双精度里不可能精确出现
   * （任何 k/10000 + 0.00005 的分母都含因子 5，不是二进制小数），
   * 所以 toFixed 的四舍五入与 Python 的 round-half-even 不会分歧。
   */
  function pyRound(value, digits) {
    if (!isFinite(value)) { return value; }
    return Number(value.toFixed(digits));
  }

  /**
   * 等价于 Python `to_braille()`，返回带统计的结果对象。
   * @param {string} text
   * @param {{number_sign?: string}|string} [opts] `number_sign`: 'run'(默认) | 'each'
   */
  function toBraille(text, opts) {
    if (typeof text !== 'string') { throw new TypeError('text 必须是字符串'); }
    var numberSign = readNumberSign(opts);

    var pieces = [];
    var unmapped = [];
    var total = 0;
    var mapped = 0;

    eachCell(text, numberSign, function (segment, braille, hit) {
      if (segment === '\n') {
        pieces.push('\n');
        return;
      }
      pieces.push(braille);
      var n = cpLength(segment);
      total += n;
      if (hit) { mapped += n; } else { unmapped.push(segment); }
    });

    return makeResult(pieces.join(''), text, unmapped, total, mapped);
  }

  /** 等价于 Python `to_braille_text()`：只要盲文字符串。 */
  function toBrailleText(text, opts) {
    return toBraille(text, opts).braille;
  }

  /** 等价于 Python `unmapped_chars()`：未覆盖字符，按首次出现顺序去重。 */
  function unmappedChars(text) {
    if (typeof text !== 'string') { throw new TypeError('text 必须是字符串'); }
    var seen = Object.create(null);
    var out = [];
    eachCell(text, 'run', function (segment, braille, hit) {
      if (!hit && !hasOwn(seen, segment)) {
        seen[segment] = true;
        out.push(segment);
      }
    });
    return out;
  }

  /** 等价于 Python `coverage_report()`。 */
  function coverageReport(text) {
    return toBraille(text).stats();
  }

  /* ------------------------------------------------------------ 折行 API */

  /** 等价于 Python 模块内的 `_tokenize()`（按 ASCII 空格切，空格各自成 token）。 */
  function tokenizeLine(line) {
    var cps = toCodePoints(line);
    var out = [];
    var token = [];
    for (var i = 0; i < cps.length; i += 1) {
      if (cps[i] === ' ') {
        if (token.length) { out.push(token); token = []; }
        out.push([' ']);
      } else {
        token.push(cps[i]);
      }
    }
    if (token.length) { out.push(token); }
    return out;
  }

  /**
   * 等价于 Python `wrap_cells()`：按盲文方数折行（默认 32，与 BRF 约定一致）。
   * 只在原有换行处与空格处断行；超长无空格片段按 width 硬折行。
   */
  function wrapCells(braille, width) {
    if (typeof braille !== 'string') { throw new TypeError('braille 必须是字符串'); }
    var w = (width === undefined || width === null) ? DEFAULT_WIDTH : width;
    if (typeof w !== 'number' || w !== w) { throw new TypeError('width 必须是数字'); }
    if (w <= 0) { throw new RangeError('width 必须为正整数'); }   // Python: ValueError

    var lines = [];
    var rawLines = braille.split('\n');
    for (var li = 0; li < rawLines.length; li += 1) {
      var current = [];
      var tokens = tokenizeLine(rawLines[li]);
      for (var ti = 0; ti < tokens.length; ti += 1) {
        var token = tokens[ti];
        if (current.length + token.length <= w) {
          current = current.concat(token);
          continue;
        }
        if (pyStrip(current.join('')) !== '') {
          lines.push(current.join(''));
        }
        while (token.length > w) {
          if (Math.floor(w) !== w) {
            // Python: TypeError: slice indices must be integers
            throw new TypeError('width 必须是整数，否则无法硬折行');
          }
          lines.push(token.slice(0, w).join(''));
          token = token.slice(w);
        }
        current = token.slice();
      }
      lines.push(current.join(''));
    }
    return lines.join('\n');
  }

  /* -------------------------------------------------------------- 导出 */

  var api = {
    // 常量
    NUMBER_SIGN: NUMBER_SIGN,
    CAPITAL_SIGN: CAPITAL_SIGN,
    BLANK_CELL: BLANK_CELL,
    DEFAULT_WIDTH: DEFAULT_WIDTH,
    DEFAULT_DATA_URL: DEFAULT_DATA_URL,
    // 数据
    load: load,
    install: install,
    ready: ready,
    tableInfo: tableInfo,
    // 转换（与 Python 逐字符等价）
    toBraille: toBraille,
    toBrailleText: toBrailleText,
    wrapCells: wrapCells,
    cellsToUnicode: cellsToUnicode,
    coverage: unmappedChars,
    unmappedChars: unmappedChars,
    coverageReport: coverageReport
  };

  return api;
});

/* ============================================================================
 * 未移植 / 已知边界（如实列出，不悄悄简化）
 * ============================================================================
 * 1. Python `BrailleResult` 是 dataclass；JS 返回普通对象，字段名保持一致
 *    （braille / source / unmapped / total_chars / mapped_chars / cell_count /
 *    coverage），并附带同名的 `stats()` 方法。`coverage` 在 JS 侧是**值**而不是
 *    getter（Python 是 property），含义相同。
 * 2. `_iter_cells()` 在 Python 里是生成器；JS 用 `eachCell(text, ns, visit)`
 *    回调实现，未导出为公开 API（公开 API 覆盖 `to_braille` / `to_braille_text` /
 *    `unmapped_chars` / `coverage_report` / `wrap_cells` / `cells_to_unicode` /
 *    `table_info` 的全部行为）。
 * 3. `wrap_cells` 对 width 为「正的非整数」（例如 8.5）的处理：Python 只在需要
 *    硬折行时抛 TypeError，本实现同样只在硬折行那一刻抛 TypeError。
 * 4. 非字符串入参：`to_braille` / `to_braille_text` 抛 TypeError（同 Python）；
 *    `wrap_cells` 抛 TypeError（Python 抛 AttributeError）——错误类型按 JS 习惯，
 *    都属"显式报错"，不会静默产出错误结果。
 * 5. 本文件不包含任何盲文语言学规则（分词、多音字消歧、标点连写规则）。
 *    这些逻辑本来就不在 `braille_zh.py` 里 —— 原实现只做「二字词表优先 + 单字表」
 *    的最长匹配，多音字消歧完全依赖表里的 `words`（例如「银行」「三重」）。
 *    因此移植后多音字行为与 Python 完全一致（同样的表、同样的匹配顺序）。
 * 6. 上游表数据本身来自 Liblouis `zh-chn.ctb`（LGPL-2.1-or-later），
 *    许可见 `ai-voice-summary/data/vendor/NOTICE.md`；本文件只是查表引擎。
 * ========================================================================= */