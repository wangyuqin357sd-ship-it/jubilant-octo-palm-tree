"""画布排版自检 v2：重叠、越界、间距、水平溢出、跳转有效性。"""
import json, io, sys

P = r"C:\Users\HP\Desktop\yuyi-preview\design\m3e-design.json"
d = json.load(io.open(P, encoding="utf-8"))
H = {"topAppBar": 88, "bottomNav": 104, "searchBar": 56, "textField": 56, "button": 56,
     "listItem": 72, "chip": 36, "text": 30, "divider": 16, "dialog": 220,
     "switch": 48, "checkbox": 40, "snackbar": 48}

def size_of(it):
    k = it["kind"]
    if k == "box":
        return it.get("size", 412), it.get("size2", 220)
    if k == "text":
        return min(380, len(it["label"]) * it.get("size", 28) * 0.62 + 8), int(it.get("size", 28) * 1.5) + 6
    if k in ("topAppBar", "bottomNav"):
        return 412, H[k]
    if k == "dialog":
        return 312, 220
    if k == "card":
        return it.get("size", 380), it.get("size2", 223)
    if k == "chip":
        return min(380, len(it["label"]) * 15 + 46), 36
    if k == "button":
        return it.get("size", len(it["label"]) * 15 + 56), 56
    if k == "iconButton":
        return 48, 48
    if k == "switch":
        return it.get("size", 380), 48
    return it.get("size", 380), H.get(k, 48)

LAYER = {"assistant": {"asst-sheet"},
         "confirm": {"cf-scrim", "cf-base", "cf-card"},
         "export": {"ex-scrim"},
         "saved": {"saved-scrim", "saved-card"},
         "audio": {"au-sheet"}, "notes": {"nt-sheet"}, "todos": {"td-sheet"}, "catalog": {"ct-sheet"},
         "home": {"home-card"}, "recording": {"rec-card-box"}, "paused": {"pause-card"}}
# 画在卡片/底板上的同心层：只检查是否越界，不参与互相间距
INNER = {"home-record-btn", "home-record-label", "rec-btn-box", "rec-txt2", "pause-btn", "pause-txt",
         "saved-title", "saved-meta", "saved-p", "saved-div"}
OVER = {"cf-scrim", "cf-base", "ex-scrim", "ex-dialog", "home-side", "home-wake"}

PRE = {"home": ("home-",), "recording": ("rec-",), "paused": ("pause-",), "assistant": ("asst-",),
       "confirm": ("cf-",), "audio": ("au-",), "notes": ("nt-",), "todos": ("td-",),
       "catalog": ("ct-",), "export": ("ex-",), "brand": ("brand-",),
       "me": ("me-",), "exports": ("exports-", "exs-", "ex-1", "ex-2", "ex-3"),
       "help": ("help-",), "saved": ("saved-",)}

def in_frame(fid, gid):
    return any(gid.startswith(p) for p in PRE[fid])

frs = {f["id"]: f for f in d["frames"]}
problems = []

for fid, f in frs.items():
    fh = f.get("h", 892)
    gs = [g for g in d["groups"] if in_frame(fid, g["id"])]
    rows = []
    for g in gs:
        gx, gy = g["x"] - f["x"], g["y"] - f["y"]
        if any(i["kind"] in ("topAppBar", "bottomNav") for i in g["items"]):
            gx = 0
        ws, hs = zip(*[size_of(i) for i in g["items"]])
        if g["items"][0]["kind"] == "box" and len(g["items"]) == 1:
            gw, gh = ws[0], hs[0]
        elif g["axis"] == "x":
            gw, gh = sum(ws) + 12 * (len(ws) - 1), max(hs)
        else:
            # 同族纵向串接：listItem 之间无额外间隙；iconButton 纵向串接按 48+12
            if g["items"][0]["kind"] == "listItem":
                gw, gh = 380, sum(hs)
            else:
                gw, gh = max(ws), sum(hs) + 12 * (len(hs) - 1)
        rows.append(dict(y0=gy, y1=gy + gh, x0=gx, x1=gx + gw, id=g["id"], items=g["items"], gh=gh, gw=gw))
    rows.sort(key=lambda r: (r["y0"], r["x0"]))

    for r in rows:
        if r["x1"] > 412:
            problems.append("%s / %s 水平越界：右边到 %.0f（宽 %.0f）" % (fid, r["id"], r["x1"], r["gw"]))
        if r["y1"] > fh:
            problems.append("%s / %s 纵向越界：底到 %.0f（帧高 %d）" % (fid, r["id"], r["y1"], fh))

    sheet = [r for r in rows
             if r["id"] in LAYER.get(fid, set())
             and r["id"].endswith("-sheet")]
    if sheet:
        sh = sheet[0]
        for r in rows:
            if r["id"] == sh["id"] or r["id"] in LAYER.get(fid, set()):
                continue
            if r["y1"] > sh["y1"]:
                problems.append("%s / %s 超出面板底板 %dpx" % (fid, r["id"], r["y1"] - sh["y1"]))

    flow = [r for r in rows if r["id"] not in LAYER.get(fid, set()) and r["id"] not in OVER
            and r["id"] not in INNER]
    for i in range(1, len(flow)):
        a, b = flow[i - 1], flow[i]
        if a["x1"] <= b["x0"] or b["x1"] <= a["x0"]:
            continue
        gap = b["y0"] - a["y1"]
        if gap < 0:
            if a["id"] in INNER or b["id"] in INNER:
                continue
            problems.append("%s / %s 与 %s 重叠 %dpx" % (fid, a["id"], b["id"], -gap))
        elif gap < 8:
            problems.append("%s / %s → %s 间距过小 %dpx" % (fid, a["id"], b["id"], gap))

    nav = [r for r in rows if any(i["kind"] == "bottomNav" for i in r["items"])]
    if nav:
        nv = nav[0]
        for r in flow:
            if r["id"] == nv["id"]:
                continue
            if r["x1"] > nv["x0"] and r["y1"] > nv["y0"] and r["y0"] < nv["y1"]:
                problems.append("%s / %s 压在底部导航上 %dpx" % (fid, r["id"], r["y1"] - nv["y0"]))

hs = {f.get("h", 892) for f in d["frames"]}
if len(hs) > 1:
    problems.append("帧高不一致：%s（画布上会显得长短不一）" % sorted(hs))

ids = set()
for g in d["groups"]:
    for i in g["items"]:
        if i["id"] in ids:
            problems.append("重复 id：%s" % i["id"])
        ids.add(i["id"])
fids = set(frs)
for g in d["groups"]:
    for i in g["items"]:
        acts = ([i["action"]] if i.get("action") else []) + list((i.get("actions") or {}).values())
        for a in acts:
            if a.get("to") not in fids and a.get("to") not in ("back", "menu", "link"):
                problems.append("%s 的跳转目标不存在：%s" % (i["id"], a.get("to")))

print("frames:%d groups:%d items:%d" % (len(d["frames"]), len(d["groups"]), sum(len(g["items"]) for g in d["groups"])))
if problems:
    print("\nlayout problems: %d" % len(problems))
    for p in problems:
        print("  [X] " + p)
    sys.exit(1)
print("\n[OK] no overlap / no overflow / spacing ok / all targets valid")
for fid, f in frs.items():
    gs = [g for g in d["groups"] if in_frame(fid, g["id"])]
    low = max((g["y"] - f["y"] + max(size_of(i)[1] for i in g["items"])) for g in gs)
    print("  %-10s h=%-5d groups=%-3d content_bottom=%-5d room=%d" % (fid, f.get("h", 892), len(gs), low, f.get("h", 892) - low))