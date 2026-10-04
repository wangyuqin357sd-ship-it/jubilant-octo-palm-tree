"""按真机比例重排全部 16 屏：430 x 932（≈ 9:19.5），内容超出部分按"可滚动"处理。"""
import json, io

P = r"C:\Users\HP\Desktop\yuyi-preview\design\m3e-design.json"
W, H, PAD, CW = 430, 932, 16, 398
GAP_S, GAP_M, GAP_L = 12, 20, 40
NAV_H = 104

KIND_H = {"topAppBar": 88, "bottomNav": NAV_H, "listItem": 72, "button": 56, "chip": 36,
          "text": 30, "divider": 16, "textField": 56, "slider": 44, "select": 56,
          "switch": 48, "searchBar": 56, "dialog": 220, "card": 120, "snackbar": 48}

def size_of(it):
    k = it["kind"]
    if k == "box":
        return it.get("size", W), it.get("size2", 220)
    if k == "text":
        return min(CW, len(it["label"]) * it.get("size", 28) * 0.62 + 8), int(it.get("size", 28) * 1.5) + 6
    if k in ("topAppBar", "bottomNav"):
        return W, KIND_H[k]
    if k == "chip":
        return min(CW, len(it["label"]) * 15 + 46), 36
    if k == "button":
        return it.get("size", len(it["label"]) * 15 + 56), 56
    if k == "card":
        return it.get("size", CW), it.get("size2", 120)
    return it.get("size", CW), KIND_H.get(k, 48)

class Screen:
    def __init__(self, fid, name, fx, fy, note, nav=None):
        self.fid, self.name, self.fx, self.fy, self.note = fid, name, fx, fy, note
        self.nav = nav                 # (group_id, selected) 底部 Tab 贴底
        self.cursor, self.groups, self.bottom = 0, [], 0
    def place(self, gid, items, y=None, gap=GAP_M, x=None, axis="x"):
        if y is None:
            y = self.cursor + (gap if self.groups else 0)
        if x is None:
            x = PAD
        self.groups.append({"id": gid, "x": self.fx + x, "y": self.fy + y, "axis": axis, "items": items})
        if axis == "y":
            step = 0 if items[0]["kind"] == "listItem" else 12
            adv = sum(size_of(i)[1] for i in items) + step * (len(items) - 1)
        else:
            adv = max(size_of(i)[1] for i in items)
        self.cursor = y + adv
        self.bottom = max(self.bottom, self.cursor)
        return self
    def overlay(self, gid, items, y=None, x=None):
        if y is None:
            y = self.cursor
        self.groups.append({"id": gid, "x": self.fx + (PAD if x is None else x), "y": self.fy + y,
                           "axis": "x", "items": items})
        return self
    def at(self, y):
        self.cursor = y
        return self

def it(id, kind, label="", icon=None, variant="filled", **kw):
    d = {"id": id, "kind": kind, "label": label, "icon": icon, "variant": variant}
    d.update(kw)
    return d

TABS = [{"icon": "home", "label": "首页"}, {"icon": "description", "label": "笔记"},
        {"icon": "graphic_eq", "label": "AI"}, {"icon": "person", "label": "我的"},
        {"icon": "mic", "label": "原音频"}]
ACT = {"tab:0": {"to": "home", "transition": "none"},
       "tab:1": {"to": "notes", "transition": "slideUp"},
       "tab:2": {"to": "assistant", "transition": "slideUp"},
       "tab:3": {"to": "me", "transition": "fade"},
       "tab:4": {"to": "audio", "transition": "slideUp"}}

def navbar(gid, sel, five=False):
    return it(gid, "bottomNav", "", None, "filled", tabs=[dict(t) for t in TABS],
              selected=sel, actions=dict(ACT))

S = []

# ═════════════ 1 首页
s = Screen("home", "首页·待机", 0, 0,
           "默认真实页面。内容在 Header 与 Tab 之间滚动；截图展示首屏。", nav=("home-nav", 0))
s.place("home-bar", [it("home-appbar", "topAppBar", "语忆", None, "filled", icon2="more_vert",
                        supporting="声音里的第二个大脑",
                        actions={"icon2": {"to": "confirm", "transition": "fade"}})])
s.at(88 + 24)
s.place("home-text", [
    it("home-date", "text", "今日 · 10月4日 星期日", None, "text", size=13, textColor="onSurfaceVariant"),
    it("home-title", "text", "今天，想记录点什么？", None, "text", size=27, bold=True),
    it("home-sub", "text", "按下录音，或者直接说“小语，开始录音”", None, "text", size=14)], axis="y")
s.place("home-wake", [it("home-wake-chip", "chip", "小语正在待机监听", "graphic_eq", "tonal", checked=False)], gap=GAP_M)
CT = s.cursor + GAP_M
s.overlay("home-card", [it("rec-card", "box", "", None, "filled", size=CW, size2=150,
                           fill="surfaceContainer", radiusTop=28, radiusBottom=28,
                           note="课堂原声记录卡片。录音按钮是唯一支持暂停/继续的入口。")], CT)
s.place("home-card-label", [it("rec-card-label", "text", "课堂原声记录", None, "text", size=12)], y=CT + 8, x=(W - 90) // 2)
s.place("home-record-btn", [it("rec-btn", "box", "", None, "filled", size=92, size2=92, fill="primary",
                               radiusTop=46, radiusBottom=46,
                               note="深墨绿圆形录音主按钮（内置白色麦克风与“开始录音”）。点击进入录音状态并本地播报提示。",
                               action={"to": "recording", "transition": "expand"})], y=CT + 44, x=(W - 92) // 2)
s.place("home-record-label", [it("rec-inner-txt", "text", "开始录音", None, "text", size=13, bold=True,
                                 note="按钮内文字，与麦克风图标一起构成按钮内容。")], y=CT + 106, x=(W - 66) // 2)
s.place("home-card-hint", [it("rec-hint", "text", "准备好了，原声会先保存，再决定是否转写。", None, "text",
                              size=13, textColor="onSurfaceVariant")], y=CT + 172, x=44)
s.place("home-card-div", [it("rec-div", "divider", "", None, "text", size=CW)], y=CT + 220)
s.place("home-card-foot", [it("rec-foot", "text", "录音中可以说：“小语，结束”", None, "text",
                              size=12, textColor="onSurfaceVariant")], y=CT + 252, x=100)
s.at(CT + 300)
s.place("home-call", [
    it("call-field", "textField", "想让小语帮你做点什么？", "diamond", "outlined", size=278,
       supporting="说“小语”，开始笔记、搜索、提醒或导出"),
    it("call-btn", "button", "呼叫", "mic", "filled", size=104,
       action={"to": "assistant", "transition": "slideUp"})], gap=GAP_M)
s.place("home-side", [
    it("side-note", "iconButton", "", "auto_awesome", "tonal", action={"to": "notes", "transition": "slideLeft"}),
    it("side-todo", "iconButton", "", "checklist", "tonal", action={"to": "todos", "transition": "slideLeft"}),
    it("side-dir", "iconButton", "", "folder_open", "tonal", action={"to": "catalog", "transition": "slideLeft"}),
    it("side-export", "iconButton", "", "download", "tonal", action={"to": "export", "transition": "fade"}),
], y=300, x=W - 60, axis="y")
S.append(s)

# ═════════════ 2 录音中
s = Screen("recording", "录音中", 522, 0,
           "点击录音后进入。卡片内出现计时与“录音中”，按钮变暂停；只有录音状态响应“小语，结束”。", nav=("rec-nav", 0))
s.place("rec-bar", [it("rec-appbar", "topAppBar", "语忆", None, "filled", icon2="more_vert",
                       supporting="声音里的第二个大脑")])
s.at(88 + 20)
s.place("rec-chips", [
    it("rec-state", "chip", "录音中 00:12", "graphic_eq", "filled", size=140),
    it("rec-end", "chip", "说“小语，结束”", "mic_off", "outlined", size=182)], gap=GAP_M)
s.place("rec-hint2", [it("rec-helper", "text", "暂停 / 继续只能用卡片上的按钮", None, "text",
                         size=12, textColor="onSurfaceVariant")], gap=GAP_S)
CT = s.cursor + GAP_M          # 卡片要落在提示文字之后，否则会压住文字
s.overlay("rec-card-box", [it("rec-card2", "box", "", None, "filled", size=CW, size2=170,
                              fill="surfaceContainer", radiusTop=28, radiusBottom=28)])
s.place("rec-card-lb", [it("rec-label2", "text", "课堂原声记录", None, "text", size=12)], y=CT + 8, x=(W - 90) // 2)
s.place("rec-btn-box", [it("rec-btn2", "box", "", None, "filled", size=92, size2=92, fill="primary",
                           radiusTop=46, radiusBottom=46,
                           note="录音中的按钮：文字变“暂停录音”，外圈脉冲动画。",
                           action={"to": "paused", "transition": "fade"})], y=CT + 44, x=(W - 92) // 2)
s.place("rec-txt2", [it("rec-inner-txt2", "text", "暂停录音", None, "text", size=13, bold=True)],
        y=CT + 106, x=(W - 66) // 2)
s.place("rec-tip2", [it("rec-tip-box", "text", "正在记录原声，先保存音频，再决定是否转写。", None, "text",
                        size=13, textColor="onSurfaceVariant")], y=CT + 172, x=48)
S.append(s)

# ═════════════ 3 录音暂停
s = Screen("paused", "录音暂停", 1044, 0, "暂停是纯 UI 状态，没有对应语音指令；原声继续保留。", nav=("pause-nav", 0))
s.place("pause-bar", [it("pause-appbar", "topAppBar", "语忆", None, "filled", icon2="more_vert",
                         supporting="声音里的第二个大脑")])
s.at(88 + 20)
s.place("pause-chips", [it("pause-state", "chip", "已暂停 00:12", "pause_circle", "tonal", checked=False)], gap=GAP_M)
s.at(s.cursor + 36)            # chip 高 36，卡片要落在它之后
PT = s.cursor + GAP_M
s.overlay("pause-card", [it("pause-card-box", "box", "", None, "filled", size=CW, size2=170,
                            fill="surfaceContainerHigh", radiusTop=28, radiusBottom=28)])
s.place("pause-lb", [it("pause-label", "text", "课堂原声记录", None, "text", size=12)], y=PT + 8, x=(W - 90) // 2)
s.place("pause-btn", [it("pause-btn-box", "box", "", None, "filled", size=92, size2=92,
                         fill="surfaceContainerHighest", radiusTop=46, radiusBottom=46,
                         note="暂停态：浅灰按钮 + 播放图标，点击继续。",
                         action={"to": "recording", "transition": "fade"})], y=PT + 44, x=(W - 92) // 2)
s.place("pause-txt", [it("pause-inner-txt", "text", "继续录音", None, "text", size=13, bold=True)],
        y=PT + 106, x=(W - 66) // 2)
s.place("pause-hint", [it("pause-hint-txt", "text", "录音已暂停，原声仍然保留，点一下继续。", None, "text",
                          size=13, textColor="onSurfaceVariant")], y=PT + 172, x=48)
S.append(s)

# ═════════════ 4 小语助手浮层
s = Screen("assistant", "小语助手浮层", 1566, 0,
           "最高层级浮层。呼叫按钮或说“小语 / 你好，小语”唤起，先播报欢迎话术，只处理预设指令。")
TOP = 300
s.overlay("asst-sheet", [it("asst-sheet-box", "box", "", None, "filled", size=W, size2=H - TOP,
                            fill="surface", radiusTop=26, radiusBottom=0)], TOP, x=0)
s.place("asst-head", [it("asst-bar", "topAppBar", "小语", "graphic_eq", "filled", icon2="close",
                         supporting="正在倾听 · 只处理预设指令",
                         actions={"icon2": {"to": "home", "transition": "slideDown"}})], y=TOP, x=0)
s.at(TOP + 88 + 20)
s.place("asst-body", [
    it("asst-welcome", "text", "您好，我是小语。请告诉我需要做什么。你可以说打开原音频、听 AI 总结、设置提醒、打开目录或导出盲文。",
       None, "text", size=15),
    it("asst-lowsig", "text", "听不懂时我不会猜，会请你换一种说法。", None, "text", size=12, textColor="onSurfaceVariant")],
    axis="y")
s.place("asst-chips1", [
    it("asst-c-help", "chip", "小语，帮助", "help", "outlined"),
    it("asst-c-repeat", "chip", "小语，重复", "replay", "outlined"),
    it("asst-c-back", "chip", "小语，返回", "arrow_back", "outlined")], gap=GAP_M)
s.place("asst-chips2", [
    it("asst-c-cancel", "chip", "小语，取消", "cancel", "outlined", size=168),
    it("asst-c-exit", "chip", "小语，退出", "logout", "outlined", size=168),
    it("asst-c-end", "chip", "小语，结束", "mic", "outlined", size=168,
       note="只在录音状态生效；助手待机时不触发退出。")], gap=GAP_S)
s.place("asst-chips3", [
    it("asst-c-audio", "chip", "原音频", "graphic_eq", "tonal", action={"to": "audio", "transition": "slideUp"}),
    it("asst-c-note", "chip", "AI 总结", "auto_awesome", "tonal", action={"to": "notes", "transition": "slideUp"}),
    it("asst-c-sum", "chip", "重新总结", "refresh", "tonal")], gap=GAP_S)
s.place("asst-chips4", [
    it("asst-c-todo", "chip", "提醒我……", "checklist", "tonal", action={"to": "todos", "transition": "slideUp"},
       note="进入 todoStart 五步录入：内容 → 确认 → 时间 → 方式 → 最终确认，存成震动提醒待办。"),
    it("asst-c-dir", "chip", "打开目录", "folder_open", "tonal", action={"to": "catalog", "transition": "slideUp"}),
    it("asst-c-export", "chip", "导出盲文", "download", "tonal", action={"to": "export", "transition": "fade"})], gap=GAP_S)
s.place("asst-chips6", [
    it("asst-c-ack", "chip", "知道了", "check", "tonal", size=150,
       action={"to": "home", "transition": "slideUp"},
       note="data-cmd=todoAck。停振、停播报、标记已提醒、关通知、回待机；与提醒弹窗里的「知道了」等效。"),
    it("asst-c-snooze", "chip", "延后十分钟", "schedule", "tonal", size=150,
       action={"to": "home", "transition": "slideUp"},
       note="data-cmd=todoSnooze。停止当前提醒，10 分钟后按同一节奏重新触发。")], gap=GAP_S)
s.place("asst-chips5", [
    it("asst-c-search", "chip", "搜索", "search", "tonal"),
    it("asst-c-tag", "chip", "加标签 / 归类", "sell", "tonal")], gap=GAP_S)
s.place("asst-foot", [it("asst-exit-btn", "button", "退出助手，回到待机", "close", "outlined", size=CW,
                         action={"to": "home", "transition": "slideDown"})], gap=GAP_M)
S.append(s)

# ═════════════ 5 我的
s = Screen("me", "我的", 2088, 0,
           "底部 Tab 的“我的”。设置项都是大触控目标；列表在 Tab 之上滚动。", nav=("me-nav-bar", 3))
s.place("me-bar", [it("me-appbar", "topAppBar", "我的", "person", "filled", icon2="settings",
                      supporting="语忆 · 声音里的第二个大脑")])
s.at(88 + 20)
s.place("me-group1", [it("me-g1", "text", "使用情况", None, "text", size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("me-stats", [
    it("me-st1", "listItem", "录音 26 段", "mic", "tonal", icon2="chevron_right", supporting="共 6 小时 12 分 · 最近一次 今天 10:24"),
    it("me-st2", "listItem", "AI 总结 22 条", "auto_awesome", "tonal", icon2="chevron_right",
       supporting="4 段还没生成总结", action={"to": "audio", "transition": "slideUp"})], gap=GAP_S, axis="y")
s.place("me-group2", [it("me-g2", "text", "朗读与通知", None, "text", size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("me-rows", [
    it("me-notify", "listItem", "通知权限与振动提醒", "notifications", "filled", switch=True, checked=True,
       supporting="通知需授权才能后台提醒；振动由手机马达执行，可先试一次振动"),
    it("me-size", "select", "正文字号", "format_size", "outlined", supporting="影响所有列表与按钮文字",
       tabs=[{"label": "标准"}, {"label": "大"}, {"label": "特大"}], selected=2),
    it("me-contrast", "listItem", "高对比度", "contrast", "filled", switch=True, checked=False,
       supporting="加深正文与辅助文字对比，适合低视力"),
    it("me-speed", "slider", "朗读语速", "speed", "filled", value=60,
       note="语音不能调节语速，只能在这里手调。")], gap=GAP_S, axis="y")
s.place("me-group3", [it("me-g3", "text", "更多", None, "text", size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("me-more", [
    it("me-exports", "listItem", "导出记录", "download", "filled", icon2="chevron_right",
       supporting="看历史 BRF 导出，可再次下载或删除", action={"to": "exports", "transition": "slideUp"}),
    it("me-help", "listItem", "帮助与语音指令", "help", "filled", icon2="chevron_right",
       supporting="可用指令、禁用指令、唤醒词说明", action={"to": "help", "transition": "slideUp"})], gap=GAP_S, axis="y")
S.append(s)

# ═════════════ 6 确认弹窗·录音转写
s = Screen("confirm", "确认弹窗·录音转写", 0, 1032,
           "录音结束保存后弹出，复述待确认内容；确认 / 暂不处理 / 取消三选一，取消后原声仍在。")
s.overlay("cf-scrim", [it("cf-scrim-box", "box", "", None, "filled", size=W, size2=H,
                          fill="inverseSurface")], 0, x=0)
s.overlay("cf-base", [it("cf-bar", "topAppBar", "语忆", None, "filled", icon2="more_vert",
                         supporting="声音里的第二个大脑")], 0, x=0)
s.overlay("cf-card", [it("cf-card-box", "box", "", None, "filled", size=CW, size2=150,
                         fill="surfaceContainer", radiusTop=28, radiusBottom=28)], 200)
s.place("cf-dialog", [it("cf-dlg", "dialog", "录音已保存", "save", "filled",
                         supporting="待确认｜录音已经保存。是否交给 AI 转换为文字？",
                         note="复述待确认内容；“交给 AI 转文字”确认后才提交。")], y=430, x=(W - 312) // 2)
s.place("cf-actions", [
    it("cf-ok", "button", "交给 AI 转文字", "check", "filled", size=296),
    it("cf-skip", "button", "暂不处理", "schedule", "text", size=296)], gap=GAP_L, x=(W - 296) // 2, axis="y")
s.place("cf-cancel", [it("cf-no", "button", "取消", "close", "outlined", size=296,
                         action={"to": "home", "transition": "fade"})], gap=GAP_S, x=(W - 296) // 2)
S.append(s)

# ═════════════ 7 原音频面板
s = Screen("audio", "原音频面板", 522, 1032,
           "目录页点“原音频”进入。存放每次录音的原始音频：播放/暂停、重命名、删除、导出，也能跳到对应的 AI 总结。")
SHEET = 300
s.overlay("au-sheet", [it("au-sheet-box", "box", "", None, "filled", size=W, size2=H - SHEET,
                          fill="surface", radiusTop=26, radiusBottom=0,
                          note="底部面板：从下往上推入。")], SHEET, x=0)
s.place("au-head", [it("au-bar", "topAppBar", "原音频", "arrow_back", "filled", icon2="close",
                       supporting="每次录音的原始音频都在这里",
                       actions={"icon": {"to": "catalog", "transition": "slideDown"},
                                "icon2": {"to": "home", "transition": "slideDown"}})], y=SHEET + 8, x=0)
s.at(SHEET + 8 + 88 + 16)
s.place("au-search", [
    it("au-search-field", "textField", "搜索原音频，或说“小语，搜索……”", "search", "outlined", size=290),
    it("au-search-btn", "button", "搜索", None, "outlined", size=104)], gap=GAP_M)
s.place("au-count", [it("au-count-txt", "text", "共 3 段原音频 · 共 26:17", None, "text",
                        size=12, textColor="onSurfaceVariant")], gap=GAP_S)
s.place("au-list", [
    it("au-1", "listItem", "高等数学 · 第3章 导数与微分", "mic", "filled", icon2="play_circle",
       supporting="原声 12:40 · 24.6 MB · 10月3日 10:24 · 已有 AI 总结"),
    it("au-2", "listItem", "英语听力精听 · Unit 5", "mic", "filled", icon2="play_circle",
       supporting="原声 08:15 · 16.1 MB · 10月3日 09:05 · 已有 AI 总结"),
    it("au-3", "listItem", "小组讨论 · 期末课题分工", "mic", "filled", icon2="play_circle",
       supporting="原声 05:22 · 10.4 MB · 10月2日 16:48 · 已有 AI 总结")], gap=GAP_M, axis="y")
S.append(s)

# ═════════════ 8 AI 总结笔记
s = Screen("notes", "AI 总结笔记", 1044, 1032,
           "全是 AI 从原音频总结提炼的内容（要点 / 摘要 / 标签），每条标着来源原音频；原文永不被改写。")
s.overlay("nt-sheet", [it("nt-sheet-box", "box", "", None, "filled", size=W, size2=H - SHEET,
                          fill="surface", radiusTop=26, radiusBottom=0)], SHEET, x=0)
s.place("nt-head", [it("nt-bar", "topAppBar", "AI 总结笔记", "arrow_back", "filled", icon2="close",
                       supporting="全部由 AI 从原音频里总结提炼",
                       actions={"icon": {"to": "catalog", "transition": "slideDown"},
                                "icon2": {"to": "home", "transition": "slideDown"}})], y=SHEET + 8, x=0)
s.at(SHEET + 8 + 88 + 16)
s.place("nt-search", [
    it("nt-search-field", "textField", "搜索 AI 总结，或说“小语，搜索……”", "search", "outlined", size=290),
    it("nt-search-btn", "button", "搜索", None, "outlined", size=104)], gap=GAP_M)
s.place("nt-count", [it("nt-count-txt", "text", "共 3 条 AI 总结", None, "text",
                        size=12, textColor="onSurfaceVariant")], gap=GAP_S)
s.place("nt-list", [
    it("nt-1", "listItem", "高等数学 · 第3章 导数与微分", "auto_awesome", "filled", icon2="volume_up",
       supporting="要点①导数=瞬时变化率 ②可导⇒连续 ③链式法则 · 待复习 · 原音频 12:40"),
    it("nt-2", "listItem", "英语听力精听 · Unit 5", "auto_awesome", "filled", icon2="volume_up",
       supporting="要点①连读弱读是主要丢分点 ②校园场景 ③三遍精听 · 听力 · 原音频 08:15"),
    it("nt-3", "listItem", "小组讨论 · 期末课题分工", "auto_awesome", "filled", icon2="volume_up",
       supporting="要点①我=资料+目录 ②小李=数据统计 ③下周三交初稿 · 课题 · 原音频 05:22")], gap=GAP_M, axis="y")
S.append(s)

# ═════════════ 9 待办面板
s = Screen("todos", "待办面板", 1566, 1032,
           "新增、查看、标记完成、删除。安卓端支持真实振动提醒：到点由手机马达按三段式节奏振动，"
           "并配合常驻系统通知与语音播报；振动需要页面在浏览器中保持运行。")
s.overlay("td-sheet", [it("td-sheet-box", "box", "", None, "filled", size=W, size2=H - 220,
                          fill="surface", radiusTop=26, radiusBottom=0)], 220, x=0)
s.place("td-head", [it("td-bar", "topAppBar", "待办", "arrow_back", "filled", icon2="close",
                       supporting="新增、查看、标记完成、删除",
                       actions={"icon": {"to": "home", "transition": "slideDown"},
                                "icon2": {"to": "home", "transition": "slideDown"}})], y=228, x=0)
s.at(228 + 88 + 16)
s.place("td-warn", [it("td-warn", "card", "安卓振动提醒",
                       "vibration", "tonal", noImage=True, size=CW, size2=130,
                       supporting="三段式节奏：短震200ms → 停100ms → 长震600ms → 停150ms → 短震200ms；"
                                  "共 3 组，组间停 2 秒，总长约 18 秒。")], gap=GAP_M)
s.place("td-notify", [it("td-notify-row", "listItem", "通知权限 · 振动开关", "notifications", "filled", switch=True,
                         checked=True, size=CW,
                         supporting="通知授权用于后台兜底；振动开关控制手机马达，可试一次振动",
                         note="对应 #notifySwitch（通知权限，沿用现有 id）与 #vibSwitch（振动提醒开关，aria-pressed）；"
                              "#vibTestBtn「试一次振动」在无 navigator.vibrate 时 hidden，"
                              "#vibState 显示振动可用性一句话状态。")], gap=GAP_M)
s.place("td-add", [
    it("td-input", "textField", "新增待办内容", "add_task", "outlined", size=290),
    it("td-add-btn", "button", "新增", "add", "filled", size=104)], gap=GAP_M)
s.place("td-list", [
    it("td-1", "listItem", "周三前把课题初稿发到群里", "radio_button_unchecked", "filled", icon2="vibration",
       supporting="震动提醒 · 10月8日 09:00 · 来自 AI 总结",
       note=".todo-mode 徽标显示「震动」；整条朗读串 todoAria()：「震动提醒，待办内容周三前把课题初稿发到群里」。"),
    it("td-2", "listItem", "复习高等数学第3章导数部分", "radio_button_unchecked", "filled", icon2="vibration",
       supporting="震动提醒 · 今天 20:00 · 来自 AI 总结",
       note=".todo-mode 徽标显示「震动」；整条朗读串 todoAria()：「震动提醒，待办内容复习高等数学第3章导数部分」。"),
    it("td-3", "listItem", "把英语 Unit 5 原文打印出来", "check_circle", "filled",
       supporting="已完成 · 手动新增")], gap=GAP_M, axis="y")
S.append(s)

# ═════════════ 10 导出记录
s = Screen("exports", "导出记录", 2088, 1032,
           "历史 BRF 导出：时间、条目、文件名、盲文级别、体积；可重新下载、全部导出、清空记录（需确认）。")
s.overlay("exports-sheet", [it("exports-sheet-box", "box", "", None, "filled", size=W, size2=H - 380,
                               fill="surface", radiusTop=26, radiusBottom=0)], 380, x=0)
s.place("exports-bar", [it("exports-appbar", "topAppBar", "导出记录", "arrow_back", "filled", icon2="close",
                           supporting="历史 BRF 导出 · 可重新下载或删除",
                           actions={"icon": {"to": "me", "transition": "slideUp"},
                                    "icon2": {"to": "home", "transition": "slideDown"}})], y=388, x=0)
s.at(388 + 88 + 16)
s.place("exports-count", [it("exports-count-txt", "text", "共 3 次导出 · 最近 今天 10:31", None, "text",
                             size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("exports-list", [
    it("ex-1x", "listItem", "高等数学 · 第3章 导数与微分", "description", "filled", icon2="download",
       supporting="今天 10:31 · yuyi-a1.brf · 中文盲文一级 · 18 KB"),
    it("ex-2x", "listItem", "英语听力精听 · Unit 5", "description", "filled", icon2="download",
       supporting="今天 09:12 · yuyi-a2.brf · 中文盲文一级 · 12 KB"),
    it("ex-3x", "listItem", "小组讨论 · 期末课题分工", "description", "filled", icon2="download",
       supporting="昨天 17:02 · yuyi-a3.brf · 中文盲文二级 · 9 KB")], gap=GAP_M, axis="y")
s.place("exports-foot", [
    it("exs-all", "button", "全部导出", "download", "tonal", size=191),
    it("exs-del", "button", "清空记录", "delete", "outlined", size=191,
       note="清空历史记录不影响音频和笔记；删除前会二次确认。")], gap=GAP_L)
S.append(s)

# ═════════════ 11 帮助与语音指令
s = Screen("help", "帮助与语音指令", 2610, 1032,
           "唤醒词、可用指令、禁用项。也是说“小语，帮助”时的完整清单。")
s.overlay("help-sheet", [it("help-sheet-box", "box", "", None, "filled", size=W, size2=H - 150,
                            fill="surface", radiusTop=26, radiusBottom=0)], 150, x=0)
s.place("help-bar", [it("help-appbar", "topAppBar", "帮助与语音指令", "arrow_back", "filled", icon2="close",
                        supporting="唤醒词 · 可用指令 · 禁用项",
                        actions={"icon": {"to": "me", "transition": "slideUp"},
                                 "icon2": {"to": "home", "transition": "slideDown"}})], y=158, x=0)
s.at(158 + 88 + 16)
s.place("help-wake", [it("help-wake", "card", "唤醒词是“小语”", "record_voice_over", "tonal",
                         noImage=True, size=CW, size2=110,
                         supporting="也可以说“你好，小语”。录音时说的话不会误唤醒助手。")], gap=GAP_M)
s.place("help-on", [
    it("help-l1", "listItem", "小语，开始录音", "mic", "filled", supporting="开始一段课堂原声记录"),
    it("help-l2", "listItem", "小语，原音频", "graphic_eq", "filled", supporting="打开原音频面板，播放或管理录音"),
    it("help-l3", "listItem", "小语，AI 总结 / 重新总结", "auto_awesome", "filled",
       supporting="打开 AI 提炼的总结，或重新提炼要点与标签"),
    it("help-l4", "listItem", "小语，搜索 / 提醒 / 导出", "search", "filled",
       supporting="搜索笔记 · 新建待办 · 导出中文盲文 BRF"),
    it("help-l5", "listItem", "小语，退出 / 返回 / 重复 / 取消", "logout", "filled",
       supporting="通用控制；结束只在录音中生效")], gap=GAP_M, axis="y")
s.place("help-off", [it("help-off", "card", "不能用的说法", "block", "outlined", noImage=True,
                        size=CW, size2=110,
                        supporting="暂停/继续录音 · 语速调快调慢 · 自由闲聊（只能用按钮或设置里手调）")], gap=GAP_M)
S.append(s)

# ═════════════ 12 目录面板（内容入口）
s = Screen("catalog", "目录面板（内容入口）", 0, 2064,
           "顶部“原音频”和“AI 总结笔记”两个主按钮分别打开对应面板；下面按目录组浏览记录条目。")
s.overlay("ct-sheet", [it("ct-sheet-box", "box", "", None, "filled", size=W, size2=H - 240,
                          fill="surface", radiusTop=26, radiusBottom=0)], 240, x=0)
s.place("ct-head", [it("ct-bar", "topAppBar", "目录", "arrow_back", "filled", icon2="close",
                       supporting="先选要看什么：原音频，还是 AI 总结笔记",
                       actions={"icon": {"to": "home", "transition": "slideDown"},
                                "icon2": {"to": "home", "transition": "slideDown"}})], y=248, x=0)
s.at(248 + 88 + 16)
s.place("ct-entries", [
    it("ct-open-audio", "button", "原音频", "graphic_eq", "tonal", size=191,
       action={"to": "audio", "transition": "slideUp"}),
    it("ct-open-notes", "button", "AI 总结笔记", "auto_awesome", "filled", size=191,
       action={"to": "notes", "transition": "slideUp"})], gap=GAP_M)
s.place("ct-hint", [it("ct-hint-txt", "text", "原音频是底稿，AI 总结是附注；改总结不会动原声。", None, "text",
                       size=12, textColor="onSurfaceVariant")], gap=GAP_S)
s.place("ct-nav", [
    it("ct-prev", "button", "上一组", "arrow_back", "outlined", size=150),
    it("ct-next", "button", "下一组", "arrow_forward", "outlined", size=150)], gap=GAP_M)
s.place("ct-group", [it("ct-group-h", "listItem", "高等数学", "folder", "tonal", icon2="volume_up", size=CW,
                        supporting="8 条记录 · 最近更新 今天")], gap=GAP_M)
s.place("ct-list", [
    it("ct-1", "listItem", "01 第1章 函数与极限", "article", "filled", icon2="chevron_right",
       supporting="今天 08:10 · 11:20"),
    it("ct-2", "listItem", "02 第2章 一元函数微分学", "article", "filled", icon2="chevron_right",
       supporting="今天 09:02 · 14:05"),
    it("ct-3", "listItem", "03 第3章 导数与微分", "article", "filled", icon2="chevron_right",
       supporting="今天 10:24 · 12:40 · 当前")], gap=GAP_S, axis="y")
S.append(s)

# ═════════════ 13 导出盲文确认
s = Screen("export", "导出盲文确认", 1044, 2064,
           "导出前先确认：用原始内容生成中文盲文 BRF，原文不会改变；AI 摘要与标签不会写进盲文文件。")
s.overlay("ex-scrim", [it("ex-scrim-box", "box", "", None, "filled", size=W, size2=H, fill="inverseSurface")], 0, x=0)
s.place("ex-dialog", [it("ex-dlg", "dialog", "导出中文盲文 BRF", "download", "filled",
                         supporting="将要执行｜将使用这条笔记的原始内容生成中文盲文 BRF。原文不会改变。确认导出吗？")],
        y=240, x=(W - 312) // 2)
s.place("ex-actions", [
    it("ex-ok", "button", "确认导出", "check", "filled", size=296),
    it("ex-other", "button", "换一段音频", "swap_horiz", "tonal", size=296)], gap=GAP_L, x=(W - 296) // 2, axis="y")
s.place("ex-cancel", [it("ex-no", "button", "取消", "close", "outlined", size=296,
                         action={"to": "home", "transition": "fade"})], gap=GAP_S, x=(W - 296) // 2)
s.place("ex-done", [it("ex-done", "card", "导出完成", "task_alt", "tonal", noImage=True, size=CW, size2=120,
                       supporting="盲文文档导出完成。原文和笔记内容没有变化。yuyi-a1.brf（中文盲文一级）")], gap=GAP_L)
S.append(s)

# ═════════════ 14 录音已保存
s = Screen("saved", "录音已保存", 2088, 2064,
           "说完“小语，结束”后立刻出现：确认原声已落盘，并给出三个去向——转文字 / 回放 / 先放着。")
s.overlay("saved-scrim", [it("saved-scrim-box", "box", "", None, "filled", size=W, size2=H, fill="inverseSurface")], 0, x=0)
s.place("saved-card", [it("saved-card", "card", "原始音频已经保存到本地", "task_alt", "tonal", noImage=True,
                          size=CW, size2=140,
                          supporting="今天 10:24 · 时长 12:40 · 24.6 MB；随时可以回放，AI 总结只是附注。")],
        y=280, x=PAD)
s.place("saved-actions", [
    it("saved-ai", "button", "交给 AI 转文字", "auto_awesome", "filled", size=CW,
       action={"to": "notes", "transition": "fade"}),
    it("saved-play", "button", "回放原音频", "play_circle", "tonal", size=CW,
       action={"to": "audio", "transition": "slideUp"}),
    it("saved-later", "button", "先放着", "schedule", "outlined", size=CW,
       action={"to": "home", "transition": "slideDown"})], y=470, gap=GAP_L, axis="y")
S.append(s)

# ═════════════ 15 规范对照页
s = Screen("brand", "色板·层级·语音指令", 1566, 2064,
           "给前端实现的对照页：颜色令牌、z-index 层级、语音指令、字号圆角、无障碍清单。")
s.place("brand-bar", [it("brand-appbar", "topAppBar", "语忆 · 实现对照", None, "filled",
                         supporting="色板 / 层级 / 语音指令 / 禁用项")])
s.place("brand-text", [
    it("brand-t1", "text", "主色 深墨绿 #2A4A40｜录音卡片 #F7F5EF｜页面底 #FFFFFF｜正文 #111111｜辅助 #777777｜品牌橙 #F07C1E",
       None, "text", size=14, bold=True),
    it("brand-t2", "text", "手机帧 430 × 932（约 9:19.5），内容边距 16，底部 Tab 高 104，内容在 Tab 之上滚动",
       None, "text", size=13),
    it("brand-t3", "text", "层级 z-index：页面 0 → 底部 Tab 20 → 右侧悬浮工具栏 30 → 面板 40 → 助手浮层 50 → 提示 60",
       None, "text", size=13),
    it("brand-t4", "text", "字号：品牌名 23/加粗 · 大标题 27/加粗 · 卡片小字 12 · 辅助 12–13 · 按钮 14–15",
       None, "text", size=13),
    it("brand-t5", "text", "圆角：卡片 28 · 面板 26 · 弹窗 22 · 按钮/输入框 14–16 · 侧边栏 20",
       None, "text", size=13),
    it("brand-t6", "text", "语音可做：开始录音 · 原音频 · AI 总结 · 重新总结 · 搜索 · 提醒我……（新建待办）· 知道了 · 延后十分钟 · 试一次振动 · 打开目录 · 跳转条目 · 打标签归类 · 删除 · 导出盲文 · 退出/返回/重复/帮助/取消 · 结束（仅录音中）",
       None, "text", size=13),
    it("brand-t7", "text", "语音禁用：暂停录音 · 继续录音 · 语速调快/调慢 · 自由闲聊 · 读取系统静音或勿扰状态 · 调用系统闹钟应用（振动只经浏览器马达 API 触发；低置信只提示重说）",
       None, "text", size=13, textColor="secondary"),
    it("brand-t8", "text", "无障碍：语义化标签 + aria-live 播报 + 提醒弹窗焦点圈定与归还 + 振动标识朗读为「震动提醒模式」 + 触控目标≥44dp（新增待办/振动控件≥48dp，提醒弹窗按钮≥56dp） + 支持 prefers-reduced-motion 与深色模式",
       None, "text", size=13)], gap=GAP_M, axis="y")
S.append(s)

# ═════════════ 16 提醒触发
s = Screen("remind", "提醒触发", 0, 3096,
           "待办到点触发的整屏提醒：#remindDlg 是 role=alertdialog 的浮层（与 #helpPanel 同级、在面板之上、Toast 之下，"
           "渲染时带 .scrim 遮罩）。先三段式振动，同刻发常驻系统通知，第一组振动结束后语音播报全文。")
s.overlay("remind-bar", [it("remind-appbar", "topAppBar", "提醒触发", "notifications_active", "filled",
                          icon2="close", supporting="到点自动弹出 · 振动 + 通知 + 语音同时进行",
                          actions={"icon": {"to": "home", "transition": "slideDown"},
                                   "icon2": {"to": "todos", "transition": "slideUp"}})], 0, x=0)
s.at(88)
s.place("remind-dialog", [it("remind-dlg", "dialog", "待办提醒", "vibration", "filled",
                             supporting="周三前把课题初稿发到群里",
                             note="对应 #remindDlg（role=alertdialog、aria-modal=true；层级与 #helpPanel 同级：.scrim 系、"
                                  "在面板之上、Toast 之下；带 .scrim 遮罩）：#remindTitle 固定为「待办提醒」，"
                                  "#remindBody 为待办全文；打开即 focus 标题、焦点圈定在弹窗内，"
                                  "关闭后焦点归还触发源；双指滑动可切换两个选项。")],
        x=(W - 312) // 2)
s.place("remind-voice", [it("remind-voice-txt", "text",
                            "语音播报：待办提醒：周三前把课题初稿发到群里（第一组振动结束后启动，慢速重复 2 遍）",
                            None, "text", size=13)], gap=GAP_M)
s.place("remind-safety", [it("remind-safe-txt", "text",
                             "静音/勿扰不影响振动；点通知、说「知道了 / 明白了 / 停」或打开待办页立即停止",
                             None, "text", size=12, textColor="onSurfaceVariant")], gap=GAP_S)
s.place("remind-actions", [
    it("remind-ack", "button", "知道了", "check", "filled", size=191,
       note="对应 #remindAckBtn（高 56dp，≥48dp）。点击＝navigator.vibrate(0) 停振并清定时器、标记已提醒、关闭常驻通知、"
            "焦点归还后回待机；播报「已知道了，提醒已停止」。语音 todoAck（知道了 / 明白了 / 停）完全等效。",
       action={"to": "home", "transition": "fade"}),
    it("remind-snooze", "button", "延后 10 分钟", "schedule", "tonal", size=191,
       note="对应 #remindSnoozeBtn（高 56dp，≥48dp）。点击＝停止当前振动与播报、snooze+1，10 分钟后按同一节奏重新触发；"
            "播报「好，10 分钟后再提醒您」。语音 todoSnooze（延后十分钟 / 等会儿再提醒）完全等效。",
       action={"to": "home", "transition": "fade"})], gap=GAP_M)
S.append(s)

# ═════════════ 输出
d = json.load(io.open(P, encoding="utf-8"))
# 按 5 列网格重排坐标（place() 用的是声明时的 fx/fy，这里做整体平移）
# 因为 place() 用的 sc.fx/fy 在排布前是 0，这里按最终坐标重建
frames, groups = [], []
for i, sc in enumerate(S):
    col, row = i % 5, i // 5
    fx, fy = col * (W + 80), row * (H + 100)
    # 底部 Tab 条：放在内容之后、贴帧底
    if sc.nav:
        gid, sel = sc.nav
        sc.groups.append({"id": gid, "x": fx, "y": fy + (H - NAV_H), "axis": "x",
                          "items": [navbar(gid + "-bar", sel)]})
    ref_x = sc.groups[0]["x"] if sc.groups else fx
    ref_y = sc.groups[0]["y"] if sc.groups else fy
    dx, dy = fx - ref_x, fy - ref_y
    for g in sc.groups:
        g["x"] += dx
        g["y"] += dy
    for g in sc.groups:
        if sc.nav and g["id"] == sc.nav[0]:
            g["y"] = fy + (H - NAV_H)
    frames.append({"id": sc.fid, "name": sc.name, "x": fx, "y": fy, "w": W, "h": H,
                   "note": sc.note, "place": "top"})
    groups.extend(sc.groups)

d["frames"] = frames
d["groups"] = groups
io.open(P, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
print("frames: %d  groups: %d  items: %d  (每个 %dx%d)" % (
    len(frames), len(groups), sum(len(g["items"]) for g in groups), W, H))
for f in frames:
    print("  %-10s %-18s (%d,%d)" % (f["id"], f["name"], f["x"], f["y"]))