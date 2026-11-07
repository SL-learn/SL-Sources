# -*- coding: utf-8 -*-
"""按「内容符号 + 站点名 + 速度符号」重排 TVBox 三条线路。

命名格式：`<内容符号><清洗名><速度符号>`
  内容符号：README/规范登记的单字符符号，见 CONTENT_RANK
  速度符号：⚡ ≤1500ms；⏱ 1500–4000ms；🐢 ≥4000ms；未实测不加速度符号
  key 一律不改，只改 name 与数组顺序。

排序主键：内容符号固定次序 → 速度档 → 原数组顺序（稳定）。
数据来源：记录/<日期>/tvbox/源体检表.csv（`逐条体检.py` 产出）。

用法：
    python 工具/源生成/重排.py --预览        # 只输出预览，不写文件
    python 工具/源生成/重排.py --执行        # 写回三条线路 api.json 并产出重排记录
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APP_DIR = os.path.join(ROOT, "apps", "tvbox")

# 内容符号与固定展示次序
CONTENT_RANK = ["🎬综合影视", "🎞电影", "📺剧集", "🎤综艺", "🎌动漫", "🎭短剧",
                "🎠少儿", "⚽体育", "📚听书", "🩺养生/生活"]
SYMBOL_OF = {
    "🎬综合影视": "🎬", "🎞电影": "🎞", "📺剧集": "📺", "🎤综艺": "🎤",
    "🎌动漫": "🎌", "🎭短剧": "🎭", "🎠少儿": "🎠", "⚽体育": "⚽",
    "📚听书": "📚", "🩺养生/生活": "🩺",
}
# 体检表里的旧标签归一到上表
ALIAS = {"🎬短剧": "🎭短剧"}

SPEED_SYMBOL = {"快": "⚡", "中": "⏱", "慢": "🐢"}
SPEED_RANK = {"⚡": 0, "⏱": 1, "": 2, "🐢": 3}
SYMBOLS = re.compile("[" + "".join(SYMBOL_OF.values()) + "⚡⏱🐢" + "]")
SEP = re.compile(r"[丨｜/]+")
TRAIL_SPEED = re.compile(r"[·\-_]?(快|中|慢)$")


def speed_of(ms: str) -> tuple[str, str]:
    try:
        v = int(float(ms))
    except (TypeError, ValueError):
        return "", "未实测"
    if v <= 1500:
        return "⚡", f"{v}ms"
    if v < 4000:
        return "⏱", f"{v}ms"
    return "🐢", f"{v}ms"


def clean_core(name: str) -> str:
    s = name.strip()
    s = SEP.sub("·", s)
    s = s.strip("·-—_ ")
    s = TRAIL_SPEED.sub("", s).strip("·-—_ ")
    s = SYMBOLS.sub("", s).strip("·-—_ ")
    s = re.sub(r"·{2,}", "·", s)
    return s[:10]


def load_health(date: str) -> dict[str, dict]:
    p = os.path.join(ROOT, "记录", date, "tvbox", "源体检表.csv")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8-sig", newline="") as f:
        return {r["key"]: r for r in csv.DictReader(f)}


def build(date: str) -> tuple[list[dict], list[dict]]:
    health = load_health(date)
    meta = json.load(open(os.path.join(APP_DIR, "version.json"), encoding="utf-8"))
    plan, report = [], []
    for ln in meta["lines"]:
        path = os.path.join(APP_DIR, ln["dir"], "api.json")
        cfg = json.load(open(path, encoding="utf-8"))
        prepared = []
        for idx, s in enumerate(cfg["sites"]):
            h = health.get(s["key"], {})
            cat = ALIAS.get(h.get("内容归类", ""), h.get("内容归类", "") or "🎬综合影视")
            if cat not in SYMBOL_OF:
                cat = "🎬综合影视"
            spd, basis = speed_of(h.get("三次均值ms", ""))
            if h.get("结论") == "需复测":
                spd, basis = "", "需复测，耗时不可作档位依据"
            core = clean_core(s["name"]) or s["key"].split("_")[-1]
            prepared.append({
                "key": s["key"], "old": s["name"], "idx": idx,
                "cat": cat, "sym": SYMBOL_OF[cat], "spd": spd,
                "basis": h.get("归类依据", "名称静态判定") + f"；速度 {basis}",
                "verdict": h.get("结论", "未实测"), "core": core,
            })
        seen: dict[str, int] = {}
        for p in prepared:
            base = p["core"]
            n = seen.get(base, 0) + 1
            seen[base] = n
            p["new"] = p["sym"] + (base if n == 1 else f"{base}·{n}") + p["spd"]
        prepared.sort(key=lambda p: (CONTENT_RANK.index(p["cat"]), SPEED_RANK[p["spd"]], p["idx"]))
        for new_idx, p in enumerate(prepared):
            report.append({"线路": ln["code"], "旧序号": p["idx"] + 1, "新序号": new_idx + 1,
                           "key": p["key"], "旧名": p["old"], "新名": p["new"],
                           "内容归类": p["cat"], "速度": p["spd"] or "未实测",
                           "依据": p["basis"], "结论": p["verdict"]})
        plan.append({"path": path, "line": ln["code"], "sites": prepared,
                     "cfg": cfg})
    return plan, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--日期", default="2026-11-07")
    ap.add_argument("--执行", action="store_true", help="写回 api.json；缺省只预览")
    ap.add_argument("--预览", action="store_true", help="只输出预览（缺省行为，显式写法）")
    ns = ap.parse_args()
    plan, report = build(ns.日期)

    print(f"{'线路':<6}{'新序':<5}{'key':<28}{'旧名':<18}{'新名'}")
    for r in report[:20]:
        print(f"{r['线路']:<6}{r['新序号']:<5}{r['key']:<28}{r['旧名']:<18}{r['新名']}")
    for p in plan:
        print(f"{p['line']}: {len(p['sites'])} 站")

    if not ns.执行:
        print("--预览：未写文件")
        return 0

    for p in plan:
        cfg = p["cfg"]
        by_key = {s["key"]: s for s in cfg["sites"]}
        new_sites = []
        for item in p["sites"]:
            s = by_key[item["key"]]
            s["name"] = item["new"]
            new_sites.append(s)
        cfg["sites"] = new_sites
        with open(p["path"], "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")

    out_dir = os.path.join(ROOT, "记录", ns.日期, "tvbox")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "重排记录.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0].keys()))
        w.writeheader()
        w.writerows(report)
    print(f"WROTE {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
