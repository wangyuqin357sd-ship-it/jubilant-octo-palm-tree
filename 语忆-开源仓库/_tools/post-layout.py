"""重排后处理：修同名 id + 跑自检。"""
import json, io, subprocess, sys

P = r"C:\Users\HP\Desktop\yuyi-preview\design\m3e-design.json"
d = json.load(io.open(P, encoding="utf-8"))

# 组 id 与组件 id 不能重名
renamed = []
for g in d["groups"]:
    for i in g["items"]:
        if i["id"] == g["id"]:
            i["id"] = i["id"] + "-card"
            renamed.append(i["id"])

io.open(P, "w", encoding="utf-8", newline="\n").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")

ids = []
for g in d["groups"]:
    ids.append(g["id"])
    ids += [i["id"] for i in g["items"]]
ids += [f["id"] for f in d["frames"]]
dup = [x for x in set(ids) if ids.count(x) > 1]
print("同名组件重命名：", ", ".join(renamed) or "无")
print("重复 id：", dup or "无")

sys.exit(subprocess.call([sys.executable, r"C:\Users\HP\Desktop\yuyi-preview\_tools\check-mobile.py"]))