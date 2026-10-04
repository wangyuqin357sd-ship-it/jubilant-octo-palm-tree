"""语忆 M3E 画布：用排版引擎重排全部 11 屏。

规则：
- 手机 412 宽，内容边距 16，内容宽 380
- 纵向节奏：同区 12，跨区 24，大区块之间 44，页脚按钮前 48
- 只有在可控层叠时才允许重叠（面板底板 / 遮罩 / 触发条），其余一律不重叠
- 帧高按内容自动计算（最小 892；底部面板类 1000），保证没有元素被裁到帧外
"""
import json, io

PATH = r"C:\Users\HP\Desktop\yuyi-preview\design\m3e-design.json"
W, PAD, CW = 412, 16, 380
GAP_S, GAP_M, GAP_L = 12, 24, 44          # 同区 / 跨区 / 大区块

# 组件默认高度（与 M3E 渲染一致）
H = {"topAppBar": 88, "bottomNav": 104, "searchBar": 56, "textField": 56, "button": 56,
     "listItem": 72, "chip": 36, "text": 30, "divider": 16, "dialog": 220,
     "switch": 48, "checkbox": 40, "box": 220, "snackbar": 48}

def height_of(it):
    if it["kind"] in ("box",):
        return it.get("size2", 220)
    if it["kind"] == "text":
        return int(it.get("size", 28) * 1.5) + 8
    return H.get(it["kind"], 48)

class Screen:
    """按阅读顺序排布；overlay 组不参与推进（它们是底板 / 遮罩）"""
    def __init__(self, fid, name, fx, fy, note, width=W):
        self.fid, self.name, self.fx, self.fy, self.note = fid, name, fx, fy, note
        self.width = width
        self.cursor = 0
        self.groups = []
        self.bottom = 0

    def place(self, gid, items, y=None, gap=GAP_M, x=None, axis="x"):
        """光标即"下一个空位的 y"；gap 表示相对于上一块底部的间距"""
        if y is None:
            y = self.cursor + (gap if self.groups else 0)
        else:
            gap = 0
        if x is None:
            x = PAD
        self.groups.append({"id": gid, "x": self.fx + x, "y": self.fy + y, "axis": axis, "items": items})
        if axis == "y":
            step = (0 if items[0]["kind"] == "listItem" else 12)
            advance = sum(height_of(i) for i in items) + step * (len(items) - 1)
        else:
            advance = max(height_of(i) for i in items)
        self.cursor = y + advance + gap
        self.bottom = max(self.bottom, self.cursor)
        return self

    def at(self, y):
        """把流光标放到指定 y（用于显式定位过的块之后）"""
        self.cursor = y
        return self

    def place_overlay(self, gid, items, y, x=None):
        """底板 / 遮罩：不推进光标"""
        if x is None:
            x = PAD
        self.groups.append({"id": gid, "x": self.fx + x, "y": self.fy + y, "axis": "x", "items": items})
        return self

    def full_width(self, kind, size=None):
        return size if size is not None else CW

def it(id, kind, label="", icon=None, variant="filled", **kw):
    d = {"id": id, "kind": kind, "label": label, "icon": icon, "variant": variant}
    d.update(kw)
    return d

def nav(id, selected, actions=None):
    d = it(id, "bottomNav", "", None, "filled", tabs=[
        {"icon": "home", "label": "首页"}, {"icon": "auto_awesome", "label": "AI 总结"},
        {"icon": "graphic_eq", "label": "AI"}, {"icon": "person", "label": "我的"}], selected=selected)
    if actions:
        d["actions"] = actions
    return d

def pair(id1, t1, i1, id2, t2, i2, w=182, gap=16):
    """一行两个按钮：182 + 16 + 182 = 380"""
    return [it(id1, "button", t1, i1, "tonal", size=w), it(id2, "button", t2, i2, "filled", size=w)]

def search_row(idf, idb, placeholder):
    """输入框 264 + 12 + 按钮 104 = 380"""
    return [it(idf, "textField", placeholder, "search", "outlined", size=264),
            it(idb, "button", "搜索", None, "outlined", size=104)]

# 底部 Tab 固定贴底：帧高 892，导航条高 104
def pin_nav(sc, gid, sel, actions):
    sc.place(gid, [nav(gid + "-bar", sel, actions)], y=892 - 104)

def sheet_box(gid, boxid, h):
    """底部面板底板：只作视觉底层，高度按内容给足"""
    return {"id": gid, "x": 0, "y": 0, "axis": "x",
            "items": [it(boxid, "box", "", None, "filled", size=W, size2=h, fill="surface",
                         radiusTop=26, radiusBottom=0,
                         note="底部面板底板：从下往上推入，遮罩下页面停住不动。")]}

S = []   # 屏幕
G = []   # 全部组

# ══════════════════════════════ 1. 首页·待机
s = Screen("home", "首页·待机", 0, 0,
           "默认真实页面：顶部品牌区、课堂原声记录卡片、底部呼叫组件、右侧常驻工具栏、底部四个 Tab。")
s.place("home-bar", [it("home-appbar", "topAppBar", "语忆", None, "filled", icon2="more_vert",
                        supporting="声音里的第二个大脑",
                        note="左上角橙色圆角方形 Logo（声波图标）＋品牌名＋slogan；右侧三点是更多操作。",
                        actions={"icon2": {"to": "confirm", "transition": "fade"}})])
s.place("home-text", [
    it("home-date", "text", "今日 · 10月3日 星期六", None, "text", size=13, textColor="onSurfaceVariant"),
    it("home-title", "text", "今天，想记录点什么？", None, "text", size=28, bold=True),
    it("home-sub", "text", "按下录音，或者直接说“小语，开始录音”", None, "text", size=14),
], gap=GAP_M, axis="y")
s.place("home-wake", [it("home-wake-chip", "chip", "小语正在待机监听", "graphic_eq", "tonal", checked=False,
                         note="待机状态下可被“小语”“你好，小语”唤起。")], gap=GAP_M)
# 录音卡片：底板 + 卡内内容（底板不推进光标）
CARD_TOP = s.cursor + GAP_M
s.place_overlay("home-card", [it("rec-card", "box", "", None, "filled", size=CW, size2=150,
                                 fill="surfaceContainer", radiusTop=28, radiusBottom=28,
                                 note="课堂原声记录卡片 #F7F5EF。录音主按钮是卡片内的圆形墨绿按钮，也是唯一支持暂停/继续的入口（无语音指令）。")], CARD_TOP)
s.place("home-card-label", [it("rec-card-label", "text", "课堂原声记录", None, "text", size=12)],
        y=CARD_TOP + 8, x=(W - 90) // 2)
s.place("home-record-btn", [it("rec-btn", "box", "", None, "filled", size=92, size2=92,
                               fill="primary", radiusTop=44, radiusBottom=44,
                               note="深墨绿圆形录音主按钮 #2A4A40（内含白色麦克风图标与“开始录音”）。点击进入录音状态，并本地播报“好的，开始录音。录音结束时请说‘小语，结束’。”",
                               action={"to": "recording", "transition": "expand"})],
        y=CARD_TOP + 44, x=(W - 92) // 2)
s.place("home-record-label", [it("rec-inner-txt", "text", "开始录音", None, "text", size=13, bold=True,
                                 note="录音按钮内的文字，与麦克风图标一起构成按钮内容。")],
        y=CARD_TOP + 106, x=(W - 66) // 2)
s.place("home-card-hint", [it("rec-hint", "text", "准备好了，原声会先保存，再决定是否转写。", None, "text",
                              size=13, textColor="onSurfaceVariant")],
        y=CARD_TOP + 172, x=40)
s.place("home-card-div", [it("rec-div", "divider", "", None, "text", size=CW)],
        y=CARD_TOP + 220)
s.place("home-card-foot", [it("rec-foot", "text", "录音中可以说：“小语，结束”", None, "text",
                              size=12, textColor="onSurfaceVariant")],
        y=CARD_TOP + 252, x=96)
s.cursor = CARD_TOP + 300
s.place("home-call", [
    it("call-field", "textField", "想让小语帮你做点什么？", "diamond", "outlined", size=264,
       supporting="说“小语”，开始笔记、搜索、提醒或导出"),
    it("call-btn", "button", "呼叫", "mic", "filled", size=104,
       note="点击 = 唤起小语语音助手，与说“小语 / 你好，小语”等价。",
       action={"to": "assistant", "transition": "slideUp"}),
], gap=GAP_L)
s.place("home-side", [
    it("side-note", "iconButton", "", "auto_awesome", "tonal",
       note="AI 总结笔记：列出 AI 从原音频总结提炼的笔记（目录页“AI 总结笔记”按钮打开的是同一个面板）。",
       action={"to": "notes", "transition": "slideLeft"}),
    it("side-todo", "iconButton", "", "checklist", "tonal",
       note="待办：新增、查看、标记完成、删除。", action={"to": "todos", "transition": "slideLeft"}),
    it("side-dir", "iconButton", "", "folder_open", "tonal",
       note="目录：内容入口，里面有“原音频”和“AI 总结笔记”两个按钮。",
       action={"to": "catalog", "transition": "slideLeft"}),
    it("side-export", "iconButton", "", "download", "tonal",
       note="导出：生成中文盲文 BRF，导出前必须确认。", action={"to": "export", "transition": "fade"}),
], y=232, x=W - 56, axis="y")
pin_nav(s, "home-nav", 0, {"tab:0": {"to": "home", "transition": "none"},
                          "tab:1": {"to": "notes", "transition": "slideUp"},
                          "tab:2": {"to": "assistant", "transition": "slideUp"}})
# home-wake：常驻待机监听药丸，贴在呼叫组件上方（不参与主光标推进）
s.bottom = max(s.bottom, 892)
S.append(s)

# ══════════════════════════════ 2. 录音中
s = Screen("recording", "录音中", 492, 0,
           "点击录音按钮后进入。卡片内出现计时与“录音中”，按钮文字变成暂停。只有录音状态才响应“小语，结束”。")
s.place("rec-bar", [it("rec-appbar", "topAppBar", "语忆", None, "filled", icon2="more_vert",
                       supporting="声音里的第二个大脑",
                       note="录音中页面结构不变，只有卡片内部换状态。")])
s.place("rec-chips", [
    it("rec-state", "chip", "录音中 00:12", "graphic_eq", "filled", size=132,
       note="计时与状态胶囊；暂停时变成“已暂停”。"),
    it("rec-end", "chip", "说“小语，结束”", "mic_off", "outlined", size=180,
       note="“小语，结束”只在录音状态生效；录音内容与助手指令相互隔离。"),
], gap=GAP_M)
s.place("rec-hint2", [it("rec-helper", "text", "提醒：暂停 / 继续只有按钮能做，语音不支持这些口令。", None, "text",
                         size=12, textColor="onSurfaceVariant")], gap=GAP_S)
CT = s.cursor + GAP_L
s.place_overlay("rec-card-box", [it("rec-card2", "box", "", None, "filled", size=CW, size2=170,
                                    fill="surfaceContainer", radiusTop=28, radiusBottom=28,
                                    note="课堂原声记录卡片（录音状态）。")], CT)
s.place("rec-card-lb", [it("rec-label2", "text", "课堂原声记录", None, "text", size=12)], y=CT + 8, x=(W - 90) // 2)
s.place("rec-btn-box", [it("rec-btn2", "box", "", None, "filled", size=92, size2=92,
                           fill="primary", radiusTop=44, radiusBottom=44,
                           note="录音中的按钮：文字变“暂停录音”，外圈有脉冲动画（prefers-reduced-motion 时关闭）。",
                           action={"to": "paused", "transition": "fade"})], y=CT + 44, x=(W - 92) // 2)
s.place("rec-txt2", [it("rec-inner-txt2", "text", "暂停录音", None, "text", size=13, bold=True,
                        note="录音按钮内的文字；图标同时换成暂停。")], y=CT + 106, x=(W - 66) // 2)
s.place("rec-tip2", [it("rec-tip-box", "text", "正在记录原声，先保存音频，再决定是否转写。", None, "text",
                        size=13, textColor="onSurfaceVariant")], y=CT + 172, x=48)
s.cursor = CT + 170
pin_nav(s, "rec-nav", 0, {"tab:1": {"to": "notes", "transition": "slideUp"}, "tab:2": {"to": "assistant", "transition": "slideUp"}})
s.bottom = max(s.bottom, 892)
S.append(s)

# ══════════════════════════════ 3. 录音暂停
s = Screen("paused", "录音暂停", 984, 0,
           "暂停是纯 UI 状态，没有对应语音指令。原声继续保留，点按钮继续录音。")
s.place("pause-bar", [it("pause-appbar", "topAppBar", "语忆", None, "filled", icon2="more_vert",
                         supporting="声音里的第二个大脑")])
s.place("pause-chips", [it("pause-state", "chip", "已暂停 00:12", "pause_circle", "tonal", checked=False,
                           note="灰色胶囊，表示已暂停，原声仍保留。")], gap=GAP_M)
PT = s.cursor + GAP_L
s.place_overlay("pause-card", [it("pause-card-box", "box", "", None, "filled", size=CW, size2=170,
                                  fill="surfaceContainerHigh", radiusTop=28, radiusBottom=28,
                                  note="卡片保持米白，按钮降级为浅灰底 + 墨绿文字。")], PT)
s.place("pause-lb", [it("pause-label", "text", "课堂原声记录", None, "text", size=12)], y=PT + 8, x=(W - 90) // 2)
s.place("pause-btn", [it("pause-btn-box", "box", "", None, "filled", size=92, size2=92,
                         fill="surfaceContainerHighest", radiusTop=44, radiusBottom=44,
                         note="暂停态：浅灰按钮 + 播放图标，点击继续录音。",
                         action={"to": "recording", "transition": "fade"})], y=PT + 44, x=(W - 92) // 2)
s.place("pause-txt", [it("pause-inner-txt", "text", "继续录音", None, "text", size=13, bold=True,
                         note="暂停按钮内的文字；图标为播放。")], y=PT + 106, x=(W - 66) // 2)
s.place("pause-hint", [it("pause-hint-txt", "text", "录音已暂停，原声仍然保留，点一下继续。", None, "text",
                          size=13, textColor="onSurfaceVariant")], y=PT + 172, x=48)
s.cursor = PT + 170
pin_nav(s, "pause-nav", 0, {"tab:0": {"to": "home", "transition": "none"}})
s.bottom = max(s.bottom, 892)
S.append(s)

# ══════════════════════════════ 4. 小语助手浮层
s = Screen("assistant", "小语助手浮层", 1476, 0,
           "最高层级浮层。呼叫按钮或说“小语 / 你好，小语”唤起，先播报欢迎话术，只处理预设指令，不做自由闲聊。")
ASST_TOP = 336
s.place_overlay("asst-sheet", [it("asst-sheet-box", "box", "", None, "filled", size=W, size2=556,
                                  fill="surface", radiusTop=26, radiusBottom=0,
                                  note="助手浮层底板，出现时页面其余部分变暗（scrim），退出后回到待机。")], ASST_TOP, x=0)
s.place("asst-head", [it("asst-bar", "topAppBar", "小语", "graphic_eq", "filled", icon2="close",
                         supporting="正在倾听 · 只处理预设指令",
                         note="关闭按钮 = “小语，退出”：关闭浮层回到页面待机。",
                         actions={"icon2": {"to": "home", "transition": "slideDown"}})], y=ASST_TOP, x=0)
s.place("asst-body", [
    it("asst-welcome", "text", "您好，我是小语。请告诉我需要做什么。你可以说打开原音频、听 AI 总结、设置提醒、打开目录或导出盲文。",
       None, "text", size=15),
    it("asst-lowsig", "text", "听不懂时我不会猜，会请你换一种说法。", None, "text", size=12, textColor="onSurfaceVariant"),
], y=ASST_TOP + 100, axis="y")
s.place("asst-chips1", [
    it("asst-c-help", "chip", "小语，帮助", "help", "outlined", note="展示当前状态可用的指令列表。"),
    it("asst-c-repeat", "chip", "小语，重复", "replay", "outlined", note="重新播报上一条提示。"),
    it("asst-c-back", "chip", "小语，返回", "arrow_back", "outlined", note="UI 回退上一步。"),
], gap=GAP_L)
s.place("asst-chips2", [
    it("asst-c-cancel", "chip", "小语，取消", "cancel", "outlined", note="关闭未确认弹窗，放弃待执行操作。"),
    it("asst-c-exit", "chip", "小语，退出", "logout", "outlined", note="关闭助手浮层回到待机。"),
    it("asst-c-end", "chip", "小语，结束", "mic", "outlined",
       note="只在录音状态生效；助手待机时该口令不触发，也不会退出助手。"),
], gap=GAP_S)
s.place("asst-chips3", [
    it("asst-c-audio", "chip", "原音频", "graphic_eq", "tonal", action={"to": "audio", "transition": "slideUp"}),
    it("asst-c-note", "chip", "AI 总结", "auto_awesome", "tonal", action={"to": "notes", "transition": "slideUp"}),
    it("asst-c-sum", "chip", "重新总结", "refresh", "tonal"),
], gap=GAP_S)
s.place("asst-chips4", [
    it("asst-c-todo", "chip", "提醒我……", "checklist", "tonal", action={"to": "todos", "transition": "slideUp"}),
    it("asst-c-dir", "chip", "打开目录", "folder_open", "tonal", action={"to": "catalog", "transition": "slideUp"}),
    it("asst-c-export", "chip", "导出盲文", "download", "tonal", action={"to": "export", "transition": "fade"}),
], gap=GAP_S)
s.place("asst-chips5", [
    it("asst-c-search", "chip", "搜索", "search", "tonal"),
    it("asst-c-tag", "chip", "加标签 / 归类", "sell", "tonal"),
], gap=GAP_S)
s.place("asst-foot", [it("asst-exit-btn", "button", "退出助手，回到待机", "close", "outlined", size=CW,
                         note="与“小语，退出”等价。", action={"to": "home", "transition": "slideDown"})],
        gap=GAP_L)
s.bottom = max(s.bottom, 892)
S.append(s)

# ══════════════════════════════ 5. 录音确认弹窗
s = Screen("confirm", "确认弹窗·录音转写", 0, 1340,
           "录音结束保存后弹出，复述待确认内容；确认/暂不处理/取消三选一，取消后原声仍在。全站修改类操作复用同一个弹窗。")
s.place_overlay("cf-scrim", [it("cf-scrim-box", "box", "", None, "filled", size=W, size2=1000,
                                fill="inverseSurface",
                                note="确认弹窗出现时页面变暗 42% 且不可操作；弹窗 z-index 高于侧边工具栏。")], 0, x=0)
s.place_overlay("cf-base", [it("cf-bar", "topAppBar", "语忆", None, "filled", icon2="more_vert",
                               supporting="声音里的第二个大脑")], 0, x=0)
s.place_overlay("cf-card", [it("cf-card-box", "box", "", None, "filled", size=CW, size2=150,
                               fill="surfaceContainer", radiusTop=28, radiusBottom=28,
                               note="底层：录音卡片，保持可见但不可点。")], 200)
s.place("cf-dialog", [it("cf-dlg", "dialog", "录音已保存", "save", "filled",
                         supporting="待确认｜录音已经保存。是否交给 AI 转换为文字？",
                         note="复述待确认内容；“交给 AI 转文字”确认后才提交，原文不会被 AI 改写。")], y=470, x=(W - 312) // 2)
s.place("cf-actions", [
    it("cf-ok", "button", "交给 AI 转文字", "check", "filled", size=296,
       action={"to": "notes", "transition": "fade"}),
    it("cf-skip", "button", "暂不处理", "schedule", "text", size=296,
       note="保留原声，不转写，关闭弹窗。"),
], gap=GAP_L, x=58, axis="y")
s.place("cf-cancel", [it("cf-no", "button", "取消", "close", "outlined", size=296,
                         note="放弃本轮操作，等同“小语，取消”。", action={"to": "home", "transition": "fade"})],
        gap=GAP_S, x=58)
s.bottom = max(s.bottom, 1000)
S.append(s)

# ══════════════════════════════ 6. 原音频面板
s = Screen("audio", "原音频面板", 492, 1340,
           "目录页点“原音频”进入。存放每次录音的原始音频：播放/暂停、重命名、删除、导出，也能跳到对应的 AI 总结。原声永远保留。")
SHEET_TOP = 240
s.place_overlay("au-sheet", [it("au-sheet-box", "box", "", None, "filled", size=W, size2=1128,
                                fill="surface", radiusTop=26, radiusBottom=0,
                                note="原音频面板：底部面板形态，从下往上推入。")], SHEET_TOP, x=0)
s.place("au-head", [it("au-bar", "topAppBar", "原音频", "arrow_back", "filled", icon2="close",
                       supporting="每次录音的原始音频都在这里 · 可播放、重命名、删除",
                       note="左上角返回 = 回到目录页；右上角关闭 = 回到首页待机。原声不参与 AI 改写，永远保留。",
                       actions={"icon": {"to": "catalog", "transition": "slideDown"},
                                "icon2": {"to": "home", "transition": "slideDown"}})], y=SHEET_TOP + 16, x=0)
s.at(SHEET_TOP + 16 + 88)
s.place("au-search", search_row("au-search-field", "au-search-btn", "搜索原音频，或说“小语，搜索……”"),
        gap=GAP_M)
s.place("au-count", [it("au-count-txt", "text", "共 3 段原音频 · 共 26:17", None, "text",
                        size=12, textColor="onSurfaceVariant")], gap=GAP_S)
def audio_card(i, title, meta, icon="play_circle"):
    return it("au-%d" % i, "listItem", title, "mic", "filled", icon2=icon, supporting=meta,
              note="点播放键试听原声；也可以重命名、导出、删除（删除需二次确认，会同时移除对应的 AI 总结）。")
s.place("au-list", [
    audio_card(1, "高等数学 · 第3章 导数与微分", "原声 12:40 · 24.6 MB · 10月3日 10:24 · 已有 AI 总结"),
    audio_card(2, "英语听力精听 · Unit 5", "原声 08:15 · 16.1 MB · 10月3日 09:05 · 已有 AI 总结"),
    audio_card(3, "小组讨论 · 期末课题分工", "原声 05:22 · 10.4 MB · 10月2日 16:48 · 已有 AI 总结"),
], gap=GAP_M, axis="y")
s.place("au-foot", [it("au-new", "button", "再录一段（语音：小语，开始录音）", "mic", "filled", size=CW,
                       note="回到首页并进入录音状态；录音按钮仍是唯一能暂停/继续的入口。",
                       action={"to": "recording", "transition": "fade"})], gap=GAP_L)
s.bottom = max(s.bottom, SHEET_TOP + 760)
S.append(s)

# ══════════════════════════════ 7. AI 总结笔记面板
s = Screen("notes", "AI 总结笔记", 984, 1340,
           "里面全是 AI 从原音频里总结提炼的内容（要点 / 摘要 / 标签 / 所属目录），每条标着来源原音频。原文永不被改写。")
s.place_overlay("nt-sheet", [it("nt-sheet-box", "box", "", None, "filled", size=W, size2=1128,
                                fill="surface", radiusTop=26, radiusBottom=0,
                                note="底部面板：从下往上推入，遮罩下页面停住不动。")], SHEET_TOP, x=0)
s.place("nt-head", [it("nt-bar", "topAppBar", "AI 总结笔记", "arrow_back", "filled", icon2="close",
                       supporting="全部由 AI 从原音频里总结提炼 · 只是附注建议",
                       note="左上角返回 = 回目录页；右上角关闭 = 回首页。可以朗读、打标签、归类、导出盲文、删除（删除需确认）。",
                       actions={"icon": {"to": "catalog", "transition": "slideDown"},
                                "icon2": {"to": "home", "transition": "slideDown"}})], y=SHEET_TOP + 16, x=0)
s.at(SHEET_TOP + 16 + 88)
s.place("nt-search", search_row("nt-search-field", "nt-search-btn", "搜索 AI 总结，或说“小语，搜索……”"), gap=GAP_M)
s.place("nt-count", [it("nt-count-txt", "text", "共 3 条 AI 总结", None, "text",
                        size=12, textColor="onSurfaceVariant")], gap=GAP_S)
s.place("nt-list", [
    it("nt-1", "listItem", "高等数学 · 第3章 导数与微分", "auto_awesome", "filled", icon2="volume_up",
       supporting="要点①导数=瞬时变化率 ②可导⇒连续 ③链式法则 · 待复习 · 原音频 12:40",
       note="AI 总结（附注）。可回溯到对应原音频；原文不变。"),
    it("nt-2", "listItem", "英语听力精听 · Unit 5", "auto_awesome", "filled", icon2="volume_up",
       supporting="要点①连读弱读是主要丢分点 ②校园场景 ③三遍精听 · 听力 · 原音频 08:15"),
    it("nt-3", "listItem", "小组讨论 · 期末课题分工", "auto_awesome", "filled", icon2="volume_up",
       supporting="要点①我=资料+目录 ②小李=数据统计 ③下周三交初稿 · 课题 · 原音频 05:22"),
], gap=GAP_M, axis="y")
s.place("nt-foot", [it("nt-new", "button", "重新总结这条音频（语音：小语，重新总结）", "refresh", "filled", size=CW,
                       note="重新提炼要点、摘要和标签；原始音频不会被修改。")], gap=GAP_L)
s.bottom = max(s.bottom, SHEET_TOP + 760)
S.append(s)

# ══════════════════════════════ 8. 待办面板
s = Screen("todos", "待办面板", 1476, 1340,
           "新增、查看、标记完成、删除。网页端只提供应用内提醒和浏览器通知，不调用系统闹钟或锁屏震动。")
s.place_overlay("td-sheet", [it("td-sheet-box", "box", "", None, "filled", size=W, size2=1128,
                                fill="surface", radiusTop=26, radiusBottom=0, note="待办面板底部面板。")], SHEET_TOP, x=0)
s.place("td-head", [it("td-bar", "topAppBar", "待办", "arrow_back", "filled", icon2="close",
                       supporting="新增、查看、标记完成、删除",
                       actions={"icon": {"to": "home", "transition": "slideDown"},
                                "icon2": {"to": "home", "transition": "slideDown"}})], y=SHEET_TOP + 16, x=0)
s.place("td-warn", [it("td-warn-box", "box", "本网页版只提供应用内提醒和浏览器通知，不会调用手机系统闹钟，也没有锁屏震动。",
                       "info", "outlined", size=CW, size2=72, fill="tertiaryContainer",
                       note="禁用项声明：网页端不能承诺系统闹钟、锁屏震动。")], gap=GAP_M)
s.place("td-notify", [it("td-notify-row", "listItem", "浏览器通知", "notifications", "filled", switch=True,
                         checked=False, size=CW,
                         supporting="开启后提醒只以浏览器通知弹出；网页关闭后不会响")], gap=GAP_M)
s.place("td-add", search_row("td-input", "td-add-btn", "新增待办内容"), gap=GAP_M)
s.place("td-list", [
    it("td-1", "listItem", "周三前把课题初稿发到群里", "radio_button_unchecked", "filled",
       supporting="应用内提醒 · 10月8日 09:00 · 来自 AI 总结",
       note="标记完成 / 删除都要先确认。"),
    it("td-2", "listItem", "复习高等数学第3章导数部分", "radio_button_unchecked", "filled",
       supporting="应用内提醒 · 今天 20:00 · 来自 AI 总结"),
    it("td-3", "listItem", "把英语 Unit 5 原文打印出来", "check_circle", "filled",
       supporting="已完成 · 手动新增"),
], gap=GAP_M, axis="y")
s.place("td-foot", [it("td-voice", "button", "语音新建（小语，提醒我……）", "mic", "outlined", size=CW)],
        gap=GAP_L)
s.bottom = max(s.bottom, SHEET_TOP + 760)
S.append(s)

# ══════════════════════════════ 9. 目录面板（内容入口）
s = Screen("catalog", "目录面板（内容入口）", 0, 2680,
           "内容入口页：顶部“原音频”和“AI 总结笔记”两个主按钮分别打开对应面板；下面按目录组浏览记录条目。")
s.place_overlay("ct-sheet", [it("ct-sheet-box", "box", "", None, "filled", size=W, size2=1128,
                                fill="surface", radiusTop=26, radiusBottom=0, note="目录面板底部面板。")], SHEET_TOP, x=0)
s.place("ct-head", [it("ct-bar", "topAppBar", "目录", "arrow_back", "filled", icon2="close",
                       supporting="先选要看什么：原音频，还是 AI 总结笔记",
                       note="内容入口：两个主按钮分别打开“原音频面板”和“AI 总结笔记面板”。",
                       actions={"icon": {"to": "home", "transition": "slideDown"},
                                "icon2": {"to": "home", "transition": "slideDown"}})], y=SHEET_TOP + 16, x=0)
s.place("ct-entries", pair("ct-open-audio", "原音频", "graphic_eq", "ct-open-notes", "AI 总结笔记", "auto_awesome"),
        gap=GAP_M)
s.place("ct-hint", [it("ct-hint-txt", "text", "原音频是底稿，AI 总结是附注；改总结不会动原声。", None, "text",
                       size=12, textColor="onSurfaceVariant")], gap=GAP_S)
s.place("ct-nav", [
    it("ct-prev", "button", "上一组", "arrow_back", "outlined", size=150, note="与语音“小语，上一组”等价。"),
    it("ct-next", "button", "下一组", "arrow_forward", "outlined", size=150,
       note="UI 切换目录组；面板顶部显示“第 2 / 3 组”。"),
], gap=GAP_M)
s.place("ct-group", [it("ct-group-h", "listItem", "高等数学", "folder", "tonal", icon2="volume_up", size=CW,
                        supporting="8 条记录 · 最近更新 今天")], gap=GAP_M)
s.place("ct-list", [
    it("ct-1", "listItem", "01 第1章 函数与极限", "article", "filled", icon2="chevron_right",
       supporting="今天 08:10 · 11:20"),
    it("ct-2", "listItem", "02 第2章 一元函数微分学", "article", "filled", icon2="chevron_right",
       supporting="今天 09:02 · 14:05"),
    it("ct-3", "listItem", "03 第3章 导数与微分", "article", "filled", icon2="chevron_right",
       supporting="今天 10:24 · 12:40 · 当前",
       note="点条目名或用“小语，打开第3章”跳转；跳转前弹确认，不改动任何内容。"),
], gap=GAP_S, axis="y")
s.place("ct-foot", [it("ct-filter", "button", "按标签筛选（小语，只看“待复习”）", "sell", "tonal", size=CW)],
        gap=GAP_L)
s.bottom = max(s.bottom, SHEET_TOP + 760)
S.append(s)

# ══════════════════════════════ 10. 导出盲文确认
s = Screen("export", "导出盲文确认", 984, 2680,
           "导出前先确认：用原始内容生成中文盲文 BRF，原文不会改变；AI 摘要与标签不会写进盲文文件。")
s.place_overlay("ex-scrim", [it("ex-scrim-box", "box", "", None, "filled", size=W, size2=1000,
                                fill="inverseSurface", note="导出确认弹窗出现时页面变暗。")], 0, x=0)
s.place("ex-dialog", [it("ex-dlg", "dialog", "导出中文盲文 BRF", "download", "filled",
                         supporting="将要执行｜将使用这条笔记的原始内容生成中文盲文 BRF。原文不会改变。确认导出吗？",
                         note="AI 摘要与标签不会写进盲文文件，只有原始口述内容。")], y=300, x=(W - 312) // 2)
s.place("ex-actions", [
    it("ex-ok", "button", "确认导出", "check", "filled", size=296),
    it("ex-other", "button", "换一段音频", "swap_horiz", "tonal", size=296,
       note="回到原音频面板重新选择。"),
], gap=GAP_L, x=58, axis="y")
s.place("ex-again", [it("ex-again-btn", "button", "改用 AI 总结导出", "auto_awesome", "tonal", size=296,
                        note="换成用 AI 总结那条笔记的原始内容导出。")], gap=GAP_S, x=58)
s.place("ex-cancel", [it("ex-no", "button", "取消", "close", "outlined", size=296,
                         action={"to": "home", "transition": "fade"})], gap=GAP_S, x=58)
s.place("ex-done", [it("ex-done-box", "box",
                       "导出完成：盲文文档导出完成。原文和笔记内容没有变化。文件名 yuyi-a1.brf（中文盲文一级/二级，UTF-8）",
                       "task_alt", "outlined", size=CW, size2=88, fill="primaryContainer")], gap=GAP_L)
s.bottom = max(s.bottom, 1000)
S.append(s)

# ══════════════════════════════ 11. 规范对照页
s = Screen("brand", "色板·层级·语音指令", 1476, 2680,
           "给前端实现的对照页：颜色令牌、z-index 层级、可用与禁用语音指令、字号与圆角规格。这一屏是说明，不需要做成页面。")
s.place("brand-title", [it("brand-bar", "topAppBar", "语忆 · 实现对照", None, "filled",
                           supporting="色板 / 层级 / 语音指令 / 禁用项")])
s.place("brand-text", [
    it("brand-t1", "text", "主色 深墨绿 #2A4A40｜录音卡片 #F7F5EF｜页面底 #FFFFFF｜正文 #111111｜辅助文字 #777777｜品牌橙 #F07C1E",
       None, "text", size=14, bold=True),
    it("brand-t2", "text", "层级 z-index：页面 0 → 底部 Tab 20 → 右侧悬浮工具栏 30 → 面板 40 → 助手浮层 50 → 提示 60",
       None, "text", size=13),
    it("brand-t3", "text", "字号：品牌名 23/加粗 · 大标题 28/加粗 · 卡片小字 12 · 辅助说明 12–13 · 按钮文字 14–15",
       None, "text", size=13),
    it("brand-t4", "text", "圆角：卡片 28 · 面板 26 · 弹窗 22 · 按钮/输入框 14–16 · 侧边栏 20",
       None, "text", size=13),
    it("brand-t5", "text", "内容结构：目录页是入口（原音频 / AI 总结笔记两个按钮）→ 原音频面板存原始音频 → AI 总结笔记面板存 AI 提炼的要点",
       None, "text", size=13),
    it("brand-t6", "text", "语音可做：开始录音 · 原音频 · AI 总结 · 重新总结 · 搜索 · 提醒 · 打开目录 · 跳转条目 · 打标签归类 · 删除 · 导出盲文 · 退出/返回/重复/帮助/取消 · 结束（仅录音中）",
       None, "text", size=13),
    it("brand-t7", "text", "语音禁用：暂停录音 · 继续录音 · 语速调快/调慢 · 自由闲聊（低置信只提示重说）",
       None, "text", size=13, textColor="secondary"),
    it("brand-t8", "text", "无障碍：语义化标签 + aria-live 播报 + 弹窗焦点圈定与归还 + 触控目标≥44dp + 支持 prefers-reduced-motion 与深色模式",
       None, "text", size=13),
], gap=GAP_L, axis="y")
s.bottom = max(s.bottom, 892)
S.append(s)

# ══════════════════════════════ 输出
# 每类屏幕的基准高度：普通页 892；底部面板页 1148；弹窗页 1000
BASE_H = {sc.fid: 1240 for sc in S}      # 全套统一 412 x 1240，画布上长度一致
FROW = {0: 0, 1: 1340, 2: 2680}
RowY = {0: 0, 1: 1340, 2: 2680}
frames = []
for sc in S:
    h = BASE_H[sc.fid]
    sc.bottom = h
    f = {"id": sc.fid, "name": sc.name, "x": sc.fx, "y": sc.fy, "h": h, "note": sc.note, "place": "top"}
    frames.append(f)
    for g in sc.groups:
        if g["id"].endswith("-sheet"):
            top = 240
            g["items"][0]["size2"] = h - top
            g["y"] = sc.fy + top
        if any(i["kind"] == "bottomNav" for i in g["items"]):
            g["y"] = sc.fy + (h - 104)             # 导航贴底
        G.append(g)

d = json.load(io.open(PATH, encoding="utf-8"))
d["frames"] = frames
d["groups"] = G
io.open(PATH, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")

print("screens:", len(frames))
for f in frames:
    print("  %-10s %-18s y=%-5d h=%d" % (f["id"], f["name"], f["y"], f["h"]))
print("groups:", len(G), "items:", sum(len(g["items"]) for g in G))