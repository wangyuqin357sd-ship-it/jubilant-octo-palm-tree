"""给画布补 4 屏：我的 / 导出记录 / 帮助与语音指令 / 录音已保存
并统一底部 Tab 的标签与跳转（首页 / 笔记 / AI / 我的），画布重排为 5 列 3 行。
"""
import json, io

P = r"C:\Users\HP\Desktop\yuyi-preview\design\m3e-design.json"
W, PAD, CW = 412, 16, 380
GAP_S, GAP_M, GAP_L = 12, 24, 44
H = {"topAppBar": 88, "bottomNav": 104, "listItem": 72, "button": 56, "chip": 36,
     "text": 30, "divider": 16, "textField": 56, "slider": 44, "select": 56,
     "switch": 48, "searchBar": 56, "dialog": 220}

def size_of(it):
    k = it["kind"]
    if k == "box":
        return it.get("size", 412), it.get("size2", 220)
    if k == "text":
        return min(380, len(it["label"]) * it.get("size", 28) * 0.62 + 8), int(it.get("size", 28) * 1.5) + 6
    if k in ("topAppBar", "bottomNav"):
        return 412, H[k]
    if k == "chip":
        return min(380, len(it["label"]) * 15 + 46), 36
    if k == "button":
        return it.get("size", len(it["label"]) * 15 + 56), 56
    return it.get("size", 380), H.get(k, 48)

class Screen:
    def __init__(self, fid, name, fx, fy, note):
        self.fid, self.name, self.fx, self.fy, self.note = fid, name, fx, fy, note
        self.cursor, self.groups, self.bottom = 0, [], 0
    def place(self, gid, items, y=None, gap=GAP_M, x=None, axis="x"):
        if y is None:
            y = self.cursor + (gap if self.groups else 0)
        if x is None:
            x = PAD
        self.groups.append({"id": gid, "x": self.fx + x, "y": self.fy + y, "axis": axis, "items": items})
        adv = (sum(size_of(i)[1] for i in items) + (0 if items[0]["kind"] == "listItem" else 12) * (len(items) - 1)
               if axis == "y" else max(size_of(i)[1] for i in items))
        self.cursor = y + adv
        self.bottom = max(self.bottom, self.cursor)
        return self
    def overlay(self, gid, items, y, x=None):
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

NAV_TABS = [{"icon": "home", "label": "首页"}, {"icon": "description", "label": "笔记"},
            {"icon": "graphic_eq", "label": "AI"}, {"icon": "person", "label": "我的"}]
NAV_ACTIONS = {"tab:0": {"to": "home", "transition": "none"},
               "tab:1": {"to": "notes", "transition": "slideUp"},
               "tab:2": {"to": "assistant", "transition": "slideUp"},
               "tab:3": {"to": "me", "transition": "fade"}}

def nav(gid, selected):
    return it(gid, "bottomNav", "", None, "filled", tabs=[dict(t) for t in NAV_TABS],
              selected=selected, actions=dict(NAV_ACTIONS))

NEW = []

# ═══════════════════ 我的 ═══════════════════
s = Screen("me", "我的", 1968, 0,
           "底部 Tab 的“我的”。个人使用情况、朗读与通知设置、导出记录入口、语音指令帮助入口。设置项都做成大触控目标，适合盲人和低视力用户操作。")
s.place("me-bar", [it("me-appbar", "topAppBar", "我的", "person", "filled", icon2="settings",
                      supporting="语忆 · 声音里的第二个大脑")])
s.place("me-group1", [it("me-g1", "text", "使用情况", None, "text", size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("me-stats", [
    it("me-st1", "listItem", "录音 26 段", "mic", "tonal", icon2="chevron_right", supporting="共 6 小时 12 分 · 最近一次 今天 10:24"),
    it("me-st2", "listItem", "AI 总结 22 条", "auto_awesome", "tonal", icon2="chevron_right",
       supporting="4 段还没生成总结", note="点进去可以看到没有总结的音频（与目录页的原音频面板一致）。",
       action={"to": "audio", "transition": "slideUp"}),
], gap=GAP_S, axis="y")
s.place("me-group2", [it("me-g2", "text", "朗读与通知", None, "text", size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("me-rows", [
    it("me-notify", "listItem", "浏览器通知", "notifications", "filled", switch=True, checked=True,
       supporting="只在应用内与浏览器通知，不调用系统闹钟、没有锁屏震动"),
    it("me-size", "select", "正文字号", "format_size", "outlined", supporting="影响所有列表与按钮文字",
       tabs=[{"label": "标准"}, {"label": "大"}, {"label": "特大"}], selected=2),
    it("me-contrast", "listItem", "高对比度", "contrast", "filled", switch=True, checked=False,
       supporting="加深正文与辅助文字对比，适合低视力"),
    it("me-speed", "slider", "朗读语速", "speed", "filled", value=60,
       note="朗读播报快慢的默认值；语音不能调节语速，只能在这里手调。"),
], gap=GAP_S, axis="y")
s.place("me-group3", [it("me-g3", "text", "更多", None, "text", size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("me-more", [
    it("me-exports", "listItem", "导出记录", "download", "filled", icon2="chevron_right",
       supporting="看历史 BRF 导出，可再次下载或删除",
       action={"to": "exports", "transition": "slideUp"}),
    it("me-help", "listItem", "帮助与语音指令", "help", "filled", icon2="chevron_right",
       supporting="可用指令、禁用指令、唤醒词说明",
       action={"to": "help", "transition": "slideUp"}),
], gap=GAP_S, axis="y")
s.place("me-hint", [it("me-hint-txt", "text", "提醒：网页版不会调用系统闹钟与锁屏震动。", None, "text",
                       size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("me-nav", [nav("me-nav-bar", 3)], y=1240 - 104)
NEW.append(s)

# ═══════════════════ 导出记录 ═══════════════════
s = Screen("exports", "导出记录", 1968, 1340,
           "从“我的 → 导出记录”进入。列出历史 BRF 导出：时间、条目、文件大小、格式；可以重新下载或删除（删除需确认）。")
s.place("exports-bar", [it("exports-appbar", "topAppBar", "导出记录", "arrow_back", "filled", icon2="close",
                           supporting="历史 BRF 导出 · 可重新下载或删除",
                           actions={"icon": {"to": "me", "transition": "slideUp"},
                                    "icon2": {"to": "home", "transition": "slideDown"}})])
s.place("exports-count", [it("exports-count-txt", "text", "共 3 次导出 · 最近 今天 10:31", None, "text",
                             size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("exports-list", [
    it("ex-1", "listItem", "高等数学 · 第3章 导数与微分", "description", "filled", icon2="download",
       supporting="今天 10:31 · yuyi-a1.brf · 中文盲文一级 · 18 KB",
       note="点右侧下载可再存一份；长按或菜单可重命名、删除。"),
    it("ex-2", "listItem", "英语听力精听 · Unit 5", "description", "filled", icon2="download",
       supporting="今天 09:12 · yuyi-a2.brf · 中文盲文一级 · 12 KB"),
    it("ex-3", "listItem", "小组讨论 · 期末课题分工", "description", "filled", icon2="download",
       supporting="昨天 17:02 · yuyi-a3.brf · 中文盲文二级 · 9 KB"),
], gap=GAP_M, axis="y")
s.place("exports-hint", [it("exports-hint-txt", "text", "出口文件都是用原始音频内容生成，AI 总结不会写进盲文。", None, "text",
                            size=12, textColor="onSurfaceVariant")], gap=GAP_M)
s.place("exports-foot", [
    it("exs-all", "button", "全部导出", "download", "tonal", size=182),
    it("exs-del", "button", "清空记录", "delete", "outlined", size=182,
       note="清空历史记录不影响音频和笔记；删除前会二次确认。"),
], gap=GAP_L)
NEW.append(s)

# ═══════════════════ 帮助与语音指令 ═══════════════════
s = Screen("help", "帮助与语音指令", 2460, 1340,
           "从“我的 → 帮助与语音指令”进入；也是说“小语，帮助”时弹出的内容页。按状态列出可用指令，并说明禁用项与唤醒词。")
s.place("help-bar", [it("help2-appbar", "topAppBar", "帮助与语音指令", "arrow_back", "filled", icon2="close",
                        supporting="唤醒词、可用指令、禁用项",
                        actions={"icon": {"to": "me", "transition": "slideUp"},
                                 "icon2": {"to": "home", "transition": "slideDown"}})])
s.place("help-wake", [it("help-wake-box", "box",
                         "唤醒词是“小语”，也可以说“你好，小语”。录音时说的内容不会误唤醒助手。",
                         "record_voice_over", "outlined", size=CW, size2=88, fill="primaryContainer",
                         note="唤醒词与录音内容相互隔离：录音里出现“小语”不会触发助手。")], gap=GAP_M)
s.place("help-on", [
    it("help-l1", "listItem", "小语，开始录音", "mic", "filled", supporting="开始一段课堂原声记录"),
    it("help-l2", "listItem", "小语，原音频", "graphic_eq", "filled", supporting="打开原音频面板，播放或管理录音"),
    it("help-l3", "listItem", "小语，AI 总结", "auto_awesome", "filled", supporting="打开 AI 从原音频提炼的总结笔记"),
    it("help-l4", "listItem", "小语，重新总结", "refresh", "filled", supporting="重新提炼要点、摘要和标签"),
    it("help-l5", "listItem", "小语，搜索……", "search", "filled", supporting="搜索原音频与 AI 总结"),
    it("help-l6", "listItem", "小语，提醒我……", "checklist", "filled", supporting="新建待办（应用内提醒）"),
    it("help-l7", "listItem", "小语，导出盲文", "download", "filled", supporting="用原始内容生成中文盲文 BRF"),
], gap=GAP_M, axis="y")
s.place("help-cmd", [it("help-cmd-txt", "text", "通用控制：退出 · 返回 · 重复 · 帮助 · 取消 · 结束（仅录音中生效）", None, "text",
                        size=13)], gap=GAP_M)
s.place("help-off-t", [it("help-off-title", "text", "不能用的说法", None, "text", size=12, textColor="secondary")], gap=GAP_M)
s.place("help-off", [
    it("help-x1", "listItem", "暂停录音 / 继续录音", "block", "outlined", supporting="只能用卡片上的按钮"),
    it("help-x2", "listItem", "语速调快 / 调慢", "block", "outlined", supporting="在“我的 → 朗读语速”里手调"),
    it("help-x3", "listItem", "自由闲聊", "block", "outlined", supporting="只处理预设指令；听不懂会请你换一种说法"),
], gap=GAP_S, axis="y")
NEW.append(s)

# ═══════════════════ 录音已保存 ═══════════════════
s = Screen("saved", "录音已保存", 1968, 2680,
           "说完“小语，结束”或点停录音后立即出现：确认原始音频已经落盘，并给出三个去向——转文字、回放、先放着。")
s.overlay("saved-scrim", [it("saved-scrim-box", "box", "", None, "filled", size=W, size2=1240,
                             fill="inverseSurface", note="提示浮层出现时页面变暗，不可操作。")], 0, x=0)
s.place("saved-card", [it("saved-card-box", "box", "", None, "filled", size=CW, size2=190,
                          fill="surfaceContainer", radiusTop=28, radiusBottom=28,
                          note="原始音频已保存的记录卡（时长、体积、时间）。")], y=300)
s.place("saved-title", [it("saved-title-txt", "text", "录音已保存", None, "text", size=18, bold=True)],
        y=326, x=(W - 92) // 2)
s.place("saved-meta", [it("saved-meta-txt", "text", "今天 10:24 · 时长 12:40 · 24.6 MB", None, "text",
                          size=12, textColor="onSurfaceVariant")], y=366, x=88)
s.place("saved-div", [it("saved-div-line", "divider", "", None, "text", size=CW)], y=408)
s.place("saved-p", [it("saved-p-txt", "text", "原始音频已经保存到本地，随时可以回放，AI 总结只是附注。", None, "text",
                       size=13, textColor="onSurfaceVariant")], y=432, x=56)
s.place("saved-actions", [
    it("saved-ai", "button", "交给 AI 转文字", "auto_awesome", "filled", size=CW,
       note="确认后才提交转写；原文不会被 AI 改写。", action={"to": "notes", "transition": "fade"}),
    it("saved-play", "button", "回放原音频", "play_circle", "tonal", size=CW,
       note="打开原音频面板并播放这一段。", action={"to": "audio", "transition": "slideUp"}),
    it("saved-later", "button", "先放着", "schedule", "outlined", size=CW,
       note="不转写也不播放，原声继续保留。", action={"to": "home", "transition": "slideDown"}),
], y=560, gap=GAP_L, axis="y")
NEW.append(s)

# ═══════════════════ 写回 ═══════════════════
d = json.load(io.open(P, encoding="utf-8"))

# 旧帧重排：5 列 x 3 行（列距 80、行距 100）
REMAP = {"home": (0, 0), "recording": (492, 0), "paused": (984, 0), "assistant": (1476, 0),
         "confirm": (0, 1340), "audio": (492, 1340), "notes": (984, 1340), "todos": (1476, 1340),
         "catalog": (0, 2680), "export": (984, 2680), "brand": (1476, 2680), "me": (1968, 0),
         "exports": (1968, 1340), "help2": (2460, 1340), "saved": (1968, 2680)}
PRE = {"home": ("home-",), "recording": ("rec-",), "paused": ("pause-",), "assistant": ("asst-",),
       "confirm": ("cf-",), "audio": ("au-",), "notes": ("nt-",), "todos": ("td-",),
       "catalog": ("ct-",), "export": ("ex-",), "brand": ("brand-",),
       "me": ("me-",), "exports": ("ex-1", "ex-2", "ex-3", "exs-", "exports-"), "help": ("help-",), "saved": ("saved-",)}

def groups_for(fid):
    out = []
    for g in d["groups"]:
        if fid == "me" and g["id"].startswith(("me-", "my-")):
            out.append(g)
        elif fid == "exports" and (g["id"].startswith("exports-") or g["id"].startswith("exs-")
                                   or g["id"] in ("ex-1", "ex-2", "ex-3")):
            out.append(g)
        elif fid == "help" and g["id"].startswith("help-"):
            out.append(g)
        elif fid == "saved" and g["id"].startswith("saved-"):
            out.append(g)
        elif fid in ("home", "recording", "paused", "assistant", "confirm", "audio", "notes",
                     "todos", "catalog", "export", "brand") and g["id"].startswith(PRE[fid]):
            out.append(g)
    return out

new_frames, new_groups = [], []
order = ["home", "recording", "paused", "assistant", "me",
         "confirm", "audio", "notes", "todos", "exports", "help2",
         "catalog", "export", "saved", "brand"]
byid = {f["id"]: f for f in d["frames"]}
for fid in order:
    key = "help" if fid == "help2" else fid
    if fid == "help2":
        sc = [x for x in NEW if x.fid == "help"][0]
        f = {"id": "help2", "name": "帮助与语音指令", "x": 2460, "y": 1340, "h": 1240,
             "note": sc.note, "place": "top"}
        gs = [g for g in sc.groups if g["id"].startswith("help-")]
        f2, g2 = f, gs
    elif fid in byid:                                   # 已有屏
        f = byid[fid]
        ox, oy = f["x"], f["y"]
        nx, ny = REMAP[fid]
        f["x"], f["y"], f["h"] = nx, ny, 1240
        gs = groups_for(fid)
        for g in gs:
            g["x"] = g["x"] - ox + nx
            g["y"] = g["y"] - oy + ny
        f2, g2 = f, gs
    else:                                               # 新屏
        sc = [x for x in NEW if x.fid == fid][0]
        f2, g2 = {"id": sc.fid, "name": sc.name, "x": sc.fx, "y": sc.fy, "h": 1240,
                  "note": sc.note, "place": "top"}, sc.groups
    new_frames.append(f2)
    new_groups.extend(g2)

# 底部 Tab 统一：标签 首页/笔记/AI/我的，跳转 首页/笔记/AI/我的
for g in new_groups:
    for i in g["items"]:
        if i["kind"] == "bottomNav":
            i["tabs"] = [dict(t) for t in NAV_TABS]
            i["actions"] = dict(NAV_ACTIONS)
            if i["id"] in ("nav", "nav2", "nav3"):
                i["selected"] = 0

d["frames"] = new_frames
d["groups"] = new_groups
io.open(P, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
print("frames: %d  groups: %d  items: %d" % (len(new_frames), len(new_groups),
      sum(len(g["items"]) for g in new_groups)))
for f in new_frames:
    print("  %-10s %-18s (%d,%d)" % (f["id"], f["name"], f["x"], f["y"]))