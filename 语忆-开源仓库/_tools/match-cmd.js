/*!
 * 语忆 · 固定指令容错匹配（零依赖，UMD）
 * ---------------------------------------------------------------------------
 * 解决的问题：页面原来用 `^...$` 整句锚定正则匹配固定指令，真人说「结束了」
 * 「小语结束吧」「帮我打开原音频」全都匹配不上，而且匹配失败时一声不响 ——
 * 用户实测反馈就是「很多次我说话小语都听不见、没有任何反应」。
 *
 * 这个文件只做一件事：**输入识别原文，输出指令 key**，认不出就老老实实返回
 * null（页面据此播报「我没听清，请再说一遍」），绝不硬塞一个 key。
 *
 * 用法（浏览器）
 *   <script src="_tools/match-cmd.js"></script>
 *   const r = MatchCmd.match("小语，帮我打开原音频", { recording: false });
 *   if (r) ROUTES[r.key] && ROUTES[r.key]();
 *   else if (MatchCmd.explain(txt).wake) say("这条不在我的固定指令里。");
 *   else say("我没听清，请再说一遍。");
 *
 * 用法（Node）
 *   const { match } = require("./match-cmd.js");
 *
 * 表体来源
 * --------
 * 下面的 TABLE 由 data/asr-phrases.json **生成**（同一份内容）。
 * 谁改了 JSON 都要重新生成；_tools/verify-match-cmd.py 会逐字段断言两者一致，
 * 不一致直接 FAIL —— 表漂移不会被放过去。
 * 页面也可以在启动时 fetch('data/asr-phrases.json') 后调 MatchCmd.useTable(doc) 覆盖。
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.MatchCmd = factory(); }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /* ======================================================================= *
   * 1) 短语表（由 data/asr-phrases.json 生成，勿手改）
   * ======================================================================= */
  var TABLE = {
    version: "1.1.0",
    wake: {
      canonical: "小语",
      words: ["小语", "小雨", "小宇", "小羽", "小玉", "小v", "晓雨", "晓宇", "小予"],
      greetings: ["你好", "您好", "嗨", "喂"]
    },
    rules: {
      weakKeyMaxLen: 2,
      weakKeyMinCoverage: 0.4,
      exactScore: 1.0,
      scoreBase: 0.5,
      coverageWeight: 0.3,
      specificityWeight: 0.2,
      specificityFullLen: 4,
      scoreCeil: 0.99,
      wakeOnlyScore: 1.0
    },
    fillers: {
      prefix: ["请你", "麻烦你", "麻烦", "帮我", "帮忙", "请问", "我想", "我要", "我", "能不能", "可不可以", "喂", "嗯", "那个", "看看", "看一下", "瞧瞧", "好了", "那么"],
      suffix: ["好吗", "好吧", "行吗", "可以吗", "谢谢", "拜托", "呗", "啦", "喽", "吧", "啊", "呀", "嘛", "哦", "呢", "了", "的", "一下"],
      infix: ["一下", "帮我", "麻烦", "请你", "请问", "我想", "能不能", "可不可以", "嗯", "那个", "就是", "这个"]
    },
    commands: [
      {
        id: "navAudio",
        text: "打开原音频",
        alts: ["原音频", "打开原始音频", "原始音频", "打开原声", "原声", "打开原音频列表", "打开原始录音"],
        keys: ["打开原音频", "打开原始音频", "打开原声", "原始音频", "原音频", "原声"],
        priority: 10,
        note: "页面直达：原音频面板。"
      },
      {
        id: "navTodo",
        text: "打开待办",
        alts: ["待办", "打开待办列表", "待办列表", "打开待办事项", "待办事项", "待办在哪"],
        keys: ["打开待办", "待办列表", "待办事项列表", "待办事项", "待办"],
        priority: 10,
        note: "与 todoStart（待办事项提醒）成对，靠“最长命中优先”避免串台。"
      },
      {
        id: "navNote",
        text: "打开笔记",
        alts: ["打开ai总结笔记", "打开总结笔记", "笔记", "打开笔记面板", "看一下笔记"],
        keys: ["打开笔记", "打开ai总结笔记", "打开总结笔记", "笔记面板", "笔记"],
        priority: 10,
        legacy: "index.html 的 ROUTES.navNote 会打开“笔记二选一”。"
      },
      {
        id: "navCatalog",
        text: "打开目录",
        alts: ["目录", "打开分类", "分类", "打开目录面板"],
        keys: ["打开目录", "打开分类", "目录", "分类"],
        priority: 10,
        legacy: "旧的 ROUTES.catalog"
      },
      {
        id: "navExports",
        text: "打开导出记录",
        alts: ["导出记录", "导出历史", "下载记录", "打开下载记录"],
        keys: ["打开导出记录", "导出记录", "导出历史", "下载记录"],
        priority: 10
      },
      {
        id: "navAiCfg",
        text: "打开接口配置",
        alts: ["接口配置", "ai接口配置", "api配置", "打开ai接口配置", "配置页"],
        keys: ["打开接口配置", "接口配置", "ai接口配置", "api配置", "配置页"],
        priority: 10
      },
      {
        id: "navHelp",
        text: "打开帮助",
        alts: ["打开帮助页", "帮助与语音指令", "打开帮助与语音指令", "指令列表"],
        keys: ["打开帮助", "帮助与语音指令", "帮助页", "指令列表"],
        priority: 10,
        note: "与 help（帮助）成对：长口令走本条，短口令走 help。"
      },
      {
        id: "navMe",
        text: "打开我的",
        alts: ["我的", "打开设置", "设置", "我的页面", "打开我的页面"],
        keys: ["打开我的", "打开设置", "我的页面", "我的", "设置"],
        priority: 10
      },
      {
        id: "navHome",
        text: "回到首页",
        alts: ["首页", "回到主页", "主页", "回首页", "打开首页"],
        keys: ["回到首页", "回到主页", "回首页", "打开首页", "首页", "主页", "home"],
        priority: 10
      },
      {
        id: "summarize",
        text: "重新总结",
        alts: ["重新总结一下", "再总结一次", "重做总结", "重新做ai总结", "重新生成总结", "做ai笔记总结", "做ai总结", "做笔记总结", "笔记总结"],
        keys: ["重新总结", "重做总结", "重新做ai总结", "重新生成总结", "做ai笔记总结", "做笔记总结", "笔记总结", "做ai总结", "再总结"],
        priority: 20,
        note: "必须比 note 的「总结」更长才能不被抢走 —— 见 priority 与“最长命中优先”。"
      },
      {
        id: "note",
        text: "AI 总结笔记",
        alts: ["ai总结笔记", "总结笔记", "ai总结", "总结", "摘要", "小结", "打开ai总结"],
        keys: ["ai总结笔记", "总结笔记", "ai总结", "总结", "摘要", "小结"],
        priority: 50,
        note: "沿用 index.html 的语义：光说「总结」是打开 AI 总结面板，不是重新总结。"
      },
      {
        id: "start",
        text: "开始录音",
        alts: ["开始记录", "开始录音吧", "我要开始录音", "小语开始录音", "开始录"],
        keys: ["开始录音", "开始记录", "开始录"],
        priority: 30,
        note: "故意不收「开始」两字：太泛，课堂上会误触发。"
      },
      {
        id: "end",
        text: "结束录音",
        alts: ["结束", "结束吧", "录完了", "停止录音", "我结束了", "好了结束", "小语结束", "小语结束吧", "完了"],
        keys: ["结束录音", "结束", "录完了", "停止录音", "完了"],
        priority: 30,
        note: "录音中唯一放行的两条指令之一。"
      },
      {
        id: "todoStart",
        text: "待办事项提醒",
        alts: ["提醒我", "新建待办", "添加待办", "加个提醒", "建个待办", "待办事项提醒我"],
        keys: ["待办事项提醒", "新建待办", "添加待办", "加个提醒", "建个待办", "提醒我"],
        priority: 20
      },
      {
        id: "todoAck",
        text: "知道了",
        alts: ["明白了", "我知道了", "好的知道了", "收到", "停", "别响了", "行了停", "行了知道了"],
        keys: ["知道了", "明白了", "我知道了", "收到", "行了停", "别响了", "停"],
        priority: 20,
        note: "录音中唯一放行的两条指令之一（提醒到点时人可能正在录音）。"
      },
      {
        id: "todoSnooze",
        text: "延后十分钟",
        alts: ["等会儿再提醒", "等会再提醒", "晚点提醒", "稍后提醒", "延后", "十分钟后再提醒", "等会儿再提醒我"],
        keys: ["延后十分钟", "十分钟后再提醒", "等会儿再提醒", "等会再提醒", "晚点提醒", "稍后提醒", "延后"],
        priority: 25
      },
      {
        id: "export",
        text: "导出盲文",
        alts: ["导出中文盲文word", "导出中文word文档", "导出盲文brf", "导出文档", "导成中文word", "导成盲文", "导出中文word", "帮我导出"],
        keys: ["导出中文盲文word", "导出中文word文档", "导出盲文brf", "导出盲文", "导出中文word", "导成中文word", "导成盲文", "导出文档", "导出", "盲文"],
        priority: 30,
        note: "与 cancel 的「先不导出」成对：先把否定说法给 cancel，再靠最长命中让「先不导出」不被本条的「导出」抢走。"
      },
      {
        id: "cancel",
        text: "取消",
        alts: ["算了", "先不导出", "不导出", "别导出", "不要了", "先不要", "不用了", "不需要", "不用", "这个不需要"],
        keys: ["先不导出", "别导出", "不导出", "这个不需要", "不需要", "不用了", "先不要", "不要了", "取消", "算了", "不用"],
        priority: 15,
        role: "deny"
      },
      {
        id: "search",
        text: "搜索",
        alts: ["查找", "找一下", "搜一下", "搜索关键词", "帮我搜索"],
        keys: ["搜索", "查找", "找一下", "搜一下"],
        priority: 40
      },
      {
        id: "repeat",
        text: "重复",
        alts: ["再说一遍", "重复一下", "再读一遍", "没听清再说一遍"],
        keys: ["重复", "再说一遍", "重复一下", "再读一遍"],
        priority: 40
      },
      {
        id: "back",
        text: "返回",
        alts: ["上一步", "返回上一步", "退回去", "返回上一级"],
        keys: ["返回上一步", "返回", "上一步", "退回去"],
        priority: 40
      },
      {
        id: "exit",
        text: "退出",
        alts: ["退出助手", "关闭助手", "再见", "不聊了"],
        keys: ["退出助手", "关闭助手", "退出", "再见", "不聊了"],
        priority: 40
      },
      {
        id: "help",
        text: "帮助",
        alts: ["你会什么", "能做什么", "帮助我", "我该说什么"],
        keys: ["帮助", "你会什么", "能做什么", "我该说什么"],
        priority: 45
      }
    ],
    dialog: [
      {
        id: "summarize",
        role: "affirm",
        text: "需要",
        alts: ["要", "可以做", "好的", "可以", "确认", "确定", "是的", "嗯", "做吧", "做ai笔记总结"],
        keys: ["需要", "可以做", "确认", "确定", "是的", "做吧", "做ai笔记总结", "要", "好的", "可以", "嗯"],
        priority: 5,
        note: "只在小语弹出确认框时生效；正文里单说一句「需要」不该触发任何动作。"
      },
      {
        id: "cancel",
        role: "deny",
        text: "不用",
        alts: ["不需要", "不用了", "先不导出", "不导出", "不要", "先不要", "算了", "不用了谢谢"],
        keys: ["不需要", "先不导出", "不导出", "不用了", "先不要", "不要", "不用", "算了"],
        priority: 5,
        note: "弹窗里的否定回答。"
      }
    ]
  };

  var VERSION = TABLE.version;

  /* 「wake」是虚拟 key：只喊了唤醒词、没说要干什么。它不是 ROUTES 里的 key，
     页面收到它应当唤起/应答助手，而不是当成「没听清」。 */
  var WAKE_KEY = "wake";

  /* 录音中只放行这两条：课堂原声里什么话都有，放行全部指令会误触发。
     沿用 index.html 原有约束（录音内容与助手指令相互隔离）。 */
  var RECORDING_ALLOWED = ["end", "todoAck"];

  var R = TABLE.rules;

  /* ======================================================================= *
   * 2) 规范化：去标点空格、全角转半角、英文小写
   * ======================================================================= */
  var PUNCT = /[\s\u3000，。、；：！？…·—～"'“”‘’（）《》【】〈〉「」『』〔〕()\[\]{}<>.,!?;:~`@#$%^&*+=|\\/_-]/g;

  function normalize(value) {
    var t = String(value == null ? "" : value);
    t = t.replace(/[\uFF01-\uFF5E]/g, function (ch) {          // 全角 ASCII → 半角
      return String.fromCharCode(ch.charCodeAt(0) - 0xFEE0);
    });
    t = t.replace(PUNCT, "");
    return t.toLowerCase();
  }

  /* ======================================================================= *
   * 3) 唤醒词：小语 / 谐音（沿用 index.html 的 WAKE_WORDS）
   * ======================================================================= */
  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  var WAKE_ALT = TABLE.wake.words.map(escapeRe).join("|");
  var GREET_ALT = TABLE.wake.greetings.map(escapeRe).join("|");
  var WAKE_RE = new RegExp("(?:" + WAKE_ALT + ")");
  var LEAD_GREET_RE = new RegExp("^(?:(?:" + GREET_ALT + ")+)");
  var LEAD_WAKE_RE = new RegExp("^(?:(?:" + WAKE_ALT + ")+)");
  var TAIL_WAKE_RE = new RegExp("(?:(?:" + WAKE_ALT + ")+)$");

  function heardWake(t) { return WAKE_RE.test(t); }

  /* 去掉句首的「你好」与唤醒词、句尾的唤醒词（「结束吧小语」这种倒装）。 */
  function stripWake(t) {
    var out = t, prev = null, guard = 0;
    while (prev !== out && guard++ < 8) {
      prev = out;
      out = out.replace(LEAD_GREET_RE, "").replace(LEAD_WAKE_RE, "");
    }
    return out.replace(TAIL_WAKE_RE, "");
  }

  /* ======================================================================= *
   * 4) 口语填充/语气词 → 生成一串等价写法（不是只剥首尾）
   * ---------------------------------------------------------------------------
   * 「打开一下待办」里的「一下」在句中，只剥首尾是剥不掉的，所以这里对
   * 前缀 / 后缀 / 句中词分别处理，并把**每一步的中间结果全部留下**当候选：
   *   我结束了 → 结束了 / 我结束 / 结束 …… 「结束」就是这么命中的。
   * 只做删除不做替换，且每个变体都要求非空，避免剥成空串乱命中。
   * ======================================================================= */
  var MAX_VARIANTS = 64;

  function buildVariants(body) {
    var seen = {}, queue = [body], guard = 0;
    seen[body] = true;
    while (queue.length && guard++ < MAX_VARIANTS * 4) {
      var v = queue.shift();
      var made = [];
      var i, f, w;
      for (i = 0; i < TABLE.fillers.infix.length; i++) {          // 句中填充：直接删
        f = TABLE.fillers.infix[i];
        if (v.length > f.length && v.indexOf(f) >= 0) made.push(v.split(f).join(""));
      }
      for (i = 0; i < TABLE.fillers.prefix.length; i++) {         // 句首填充
        f = TABLE.fillers.prefix[i];
        if (v.length > f.length && v.indexOf(f) === 0) made.push(v.slice(f.length));
      }
      for (i = 0; i < TABLE.fillers.suffix.length; i++) {         // 句尾语气词
        f = TABLE.fillers.suffix[i];
        if (v.length > f.length && v.slice(-f.length) === f) made.push(v.slice(0, v.length - f.length));
      }
      for (i = 0; i < made.length; i++) {
        w = made[i];
        if (!w || seen[w]) continue;
        if (Object.keys(seen).length >= MAX_VARIANTS) break;
        seen[w] = true;
        queue.push(w);
      }
    }
    return Object.keys(seen);
  }

  /* ======================================================================= *
   * 5) 打分
   * ---------------------------------------------------------------------------
   * score 是 0~1 的可比分数，页面用它决定「要不要请用户重说」：
   *   = 1.00  识别文本与标准说法/口语变体**完全一致**（去掉唤醒词和标点之后）
   *   < 1.00  只是命中了关键片段：0.5 + 0.3*覆盖率 + 0.2*具体度
   *           覆盖率 = 关键片段长度 / 这个变体的长度（说了一堆废话但只蹭到一个词 → 分低）
   *           具体度 = min(1, 关键片段长度 / 4)（4 字以上的关键词算“够具体”）
   * 页面建议阈值：>= 0.6 直接执行；0.5~0.6 执行但提示「我听到的是……对吗」；
   *              本函数返回 null 就是没听清，直接请用户重说。
   * ======================================================================= */
  function scoreOf(keyLen, formLen) {
    var coverage = keyLen / Math.max(1, formLen);
    var specificity = Math.min(1, keyLen / R.specificityFullLen);
    return Math.min(R.scoreCeil,
      R.scoreBase + R.coverageWeight * coverage + R.specificityWeight * specificity);
  }

  /* 短关键词（≤ weakKeyMaxLen 字）在没有唤醒词时不可靠：
     「总结」「目录」「导出」这类词在课堂原声里随便就会冒出来。
     规则：没有唤醒词时，短关键词必须覆盖整句的 weakKeyMinCoverage 以上才算数
     （「总结」单说 → 覆盖率 1.0，算；「我们总结一下今天的内容」→ 覆盖率 0.22，不算）。
     注意：精确命中标准说法/口语变体的分支**不受**这条限制 —— 表里写了就是认。 */
  function weakKeyRejected(keyLen, formLen, wake) {
    if (wake) return false;
    if (keyLen > R.weakKeyMaxLen) return false;
    return (keyLen / Math.max(1, formLen)) < R.weakKeyMinCoverage;
  }

  /* ======================================================================= *
   * 6) 单条指令打分 + 全表竞争
   * ---------------------------------------------------------------------------
   * 优先级规则（避免串台，按顺序）：
   *   ① 精确命中（等于标准说法或某个口语变体）永远赢过片段命中；
   *   ② 片段命中里，score 高的赢 → score 里含“关键片段长度”，所以
   *      「待办事项提醒」(6字) 抢得过「待办」(2字)、「重新总结」(4字) 抢得过「总结」(2字)；
   *   ③ 同分比关键片段长度；
   *   ④ 再同分比表里的 priority（数字小的优先）；
   *   ⑤ 最后按表里的先后顺序（也就是 index.html 里 nav* 在前的既有次序）。
   * ======================================================================= */
  function bestForCommand(cmd, forms, wake) {
    var i, j, f, k, best = null;
    var exacts = [cmd.text].concat(cmd.alts || []);
    for (i = 0; i < forms.length; i++) {                       // ① 精确
      f = forms[i];
      for (j = 0; j < exacts.length; j++) {
        if (normalize(exacts[j]) === f) {
          return { key: f, exact: true, score: R.exactScore, matched: normalize(exacts[j]), form: f };
        }
      }
    }
    for (i = 0; i < forms.length; i++) {                       // ② 片段
      f = forms[i];
      for (j = 0; j < (cmd.keys || []).length; j++) {
        k = normalize(cmd.keys[j]);
        if (!k || f.indexOf(k) < 0) continue;
        if (weakKeyRejected(k.length, f.length, wake)) continue;
        var s = scoreOf(k.length, f.length);
        if (!best || s > best.score || (s === best.score && k.length > best.matched.length)) {
          best = { key: k, exact: false, score: s, matched: k, form: f };
        }
      }
    }
    return best;
  }

  function poolFor(opts) {
    var pool = TABLE.commands.slice();
    if (opts && opts.dialog) pool = pool.concat(TABLE.dialog);   // 弹窗应答词只在弹窗打开时进池
    if (opts && opts.recording) {
      /* 录音中只放行 end / todoAck。注意只过滤 commands：
         弹窗应答词本来就要求 opts.dialog 显式打开，而 index.html 的原逻辑
         也是「弹窗优先于录音限制」。 */
      pool = pool.filter(function (c) { return RECORDING_ALLOWED.indexOf(c.id) >= 0; });
    }
    return pool;
  }

  function rank(a, b) {
    if (b.score !== a.score) return b.score - a.score;                  // ② score
    if (b.matched.length !== a.matched.length) return b.matched.length - a.matched.length; // ③ 更长
    if (a.priority !== b.priority) return a.priority - b.priority;      // ④ priority 小者先
    return a.index - b.index;                                           // ⑤ 表内次序
  }

  function evaluate(rawText, opts) {
    opts = opts || {};
    var t = normalize(rawText);
    var detail = { normalized: t, wake: false, body: "", best: null, runnerUp: null, candidates: [], rejected: null };
    if (!t) return detail;

    detail.wake = heardWake(t);
    var body = stripWake(t);
    detail.body = body;

    if (!body) {                                   // 只喊了唤醒词 → 唤起/应答助手
      var wakeOnly = { key: WAKE_KEY, exact: true, score: R.wakeOnlyScore, matched: "",
                       form: "", id: WAKE_KEY, text: TABLE.wake.canonical, role: null,
                       priority: 0, index: -1 };
      detail.candidates = [wakeOnly];
      detail.best = wakeOnly;
      return detail;
    }
    if (opts.requireWake && !detail.wake) { detail.rejected = "requireWake"; return detail; }

    var forms = buildVariants(body);
    detail.forms = forms;
    var pool = poolFor(opts);
    var hits = [];
    for (var i = 0; i < pool.length; i++) {
      var cmd = pool[i];
      var hit = bestForCommand(cmd, forms, detail.wake);
      if (!hit) continue;
      hit.id = cmd.id;
      hit.text = cmd.text;
      hit.role = cmd.role || null;
      hit.priority = (typeof cmd.priority === "number") ? cmd.priority : 100;
      hit.index = i;
      hits.push(hit);
    }
    hits.sort(rank);
    detail.candidates = hits;
    detail.best = hits[0] || null;
    detail.runnerUp = hits[1] || null;
    return detail;
  }

  /* ======================================================================= *
   * 7) 对外接口
   * ======================================================================= */

  /* match(rawText, opts) → {key, text, score, wake, role} | null
   *   opts.recording   录音中（只放行 end / todoAck）
   *   opts.dialog      小语的确认弹窗正开着（放行「需要」「不用」这类应答词）
   *   opts.requireWake 必须听到唤醒词才认（想彻底防误触发时打开）
   * 认不出任何指令 → null（页面据此播报「我没听清，请再说一遍」）。
   * 只想唤醒、没说要干什么 → {key:"wake"}。 */
  function match(rawText, opts) {
    var d = evaluate(rawText, opts);
    if (!d.best) return null;
    if (d.best.key === WAKE_KEY) {
      return { key: WAKE_KEY, text: TABLE.wake.canonical, score: R.wakeOnlyScore, wake: true, role: null };
    }
    return {
      key: d.best.id,
      text: d.best.text,
      score: Math.round(d.best.score * 1000) / 1000,
      wake: d.wake,
      role: d.best.role,
      matched: d.best.matched
    };
  }

  /* explain(rawText, opts) → 诊断信息。match() 返回 null 时用它区分
   * 「听到了小语但这条不认识」和「压根没听清」，也方便排查串台。 */
  function explain(rawText, opts) {
    var d = evaluate(rawText, opts);
    return {
      normalized: d.normalized,
      wake: d.wake,
      body: d.body,
      forms: d.forms || [],
      rejected: d.rejected || null,
      best: d.best ? { key: d.best.key === WAKE_KEY ? WAKE_KEY : d.best.id, score: round3(d.best.score),
                       exact: d.best.exact, matched: d.best.matched, form: d.best.form } : null,
      runnerUp: d.runnerUp ? { key: d.runnerUp.id, score: round3(d.runnerUp.score),
                               exact: d.runnerUp.exact, matched: d.runnerUp.matched } : null,
      candidates: d.candidates.map(function (c) {
        return { key: c.key === WAKE_KEY ? WAKE_KEY : c.id, score: round3(c.score), exact: c.exact, matched: c.matched };
      })
    };
  }

  function round3(n) { return Math.round(n * 1000) / 1000; }

  /* 用 data/asr-phrases.json 覆盖内嵌表（页面可选；不调用就用内嵌的那份）。 */
  function useTable(doc) {
    if (!doc || !doc.commands || !doc.commands.length) throw new Error("useTable: 不是有效的短语表");
    TABLE = doc;
    R = TABLE.rules;
    var alt = TABLE.wake.words.map(escapeRe).join("|");
    var greet = TABLE.wake.greetings.map(escapeRe).join("|");
    WAKE_RE = new RegExp("(?:" + alt + ")");
    LEAD_GREET_RE = new RegExp("^(?:(?:" + greet + ")+)");
    LEAD_WAKE_RE = new RegExp("^(?:(?:" + alt + ")+)");
    TAIL_WAKE_RE = new RegExp("(?:(?:" + alt + ")+)$");
    return true;
  }

  /* 把表摊平成给 Vosk 固定语法用的短语列表（标准说法 + 口语变体 + 唤醒词）。 */
  function phrasesForAsr() {
    var out = [], seen = {};
    function push(s) { if (s && !seen[s]) { seen[s] = 1; out.push(s); } }
    TABLE.commands.concat(TABLE.dialog).forEach(function (c) {
      push(c.text);
      (c.alts || []).forEach(push);
    });
    push(TABLE.wake.canonical);
    TABLE.wake.greetings.forEach(function (g) { push(g + TABLE.wake.canonical); });
    return out;
  }

  return {
    VERSION: VERSION,
    WAKE_KEY: WAKE_KEY,
    RECORDING_ALLOWED: RECORDING_ALLOWED,
    TABLE: TABLE,
    match: match,
    explain: explain,
    normalize: normalize,
    buildVariants: buildVariants,
    phrasesForAsr: phrasesForAsr,
    useTable: useTable
  };
});