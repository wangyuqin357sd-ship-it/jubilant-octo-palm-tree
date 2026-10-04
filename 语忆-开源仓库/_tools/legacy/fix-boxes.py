"""把“只有色块没有文字”的 box 说明块换成 card（label + supporting 会真正渲染）。"""
import json, io

P = r"C:\Users\HP\Desktop\yuyi-preview\design\m3e-design.json"
d = json.load(io.open(P, encoding="utf-8"))

def card(id, label, supporting, icon, variant="tonal", h=110, w=380, note=None, **kw):
    x = {"id": id, "kind": "card", "label": label, "icon": icon, "variant": variant,
         "supporting": supporting, "size": w, "size2": h, "noImage": True}
    if note:
        x["note"] = note
    x.update(kw)
    return x

# 需要替换的：id → (label, supporting, icon, 高度)
REPLACE = {
    # 待办：禁用项声明
    "td-warn-box": ("网页版提醒能力有限",
                    "只提供应用内提醒和浏览器通知；不会调用手机系统闹钟，也没有锁屏震动。",
                    "info", 110),
    # 导出记录：BRF 说明
    "exports-what-box": ("BRF 是什么",
                         "标准盲文文件，用一级或二级中文盲文；文件里只有原始口述内容，AI 总结与标签不会写进去。",
                         "info", 120),
    # 帮助：唤醒词
    "help-wake-box": ("唤醒词是“小语”",
                      "也可以说“你好，小语”。录音时说的话不会误唤醒助手。",
                      "record_voice_over", 110),
    # 录音已保存：保存卡
    "saved-card-box": ("原始音频已经保存到本地",
                       "随时可以回放；AI 总结只是附注，不会改写原话。",
                       "task_alt", 150),
    # 导出完成提示（导出页）
    "ex-done-box": ("导出完成",
                    "盲文文档导出完成。原文和笔记内容没有变化。文件名 yuyi-a1.brf（中文盲文一级，UTF-8）。",
                    "task_alt", 130),
}

changed = []
for g in d["groups"]:
    items = []
    for i in g["items"]:
        if i["id"] in REPLACE and i["kind"] == "box":
            label, sup, icon, h = REPLACE[i["id"]]
            new = card(i["id"], label, sup, icon, variant="tonal", h=h)
            new["note"] = i.get("note", "")
            items.append(new)
            changed.append(i["id"])
        else:
            items.append(i)
    g["items"] = items

io.open(P, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
print("替换为可渲染文字的 card：", ", ".join(changed))