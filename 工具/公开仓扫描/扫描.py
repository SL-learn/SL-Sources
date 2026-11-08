"""公开仓扫描门禁：查私有痕迹 + 查悬空引用。

用法（仓库根执行）：
    python 工具/公开仓扫描/扫描.py --词表 <私有域词表路径>
    python 工具/公开仓扫描/扫描.py --词表 ... --根 <被测目录>

退出码：0 通过；1 有命中。
词表属私有域，**不入公开仓**；脚本里不内置任何私有词。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

TEXT_EXT = {".md", ".txt", ".csv", ".json", ".py", ".gitignore", ".yml", ".yaml"}
SKIP_DIRS = {".git", "__pycache__", "_分析", "备份", ".idea", ".vscode"}
FORBIDDEN_NAMES = [
    re.compile(r".*清单\.csv$"),
    re.compile(r"^站点目录.*\.(json|csv)$"),
    re.compile(r"^探活明细.*"),
    re.compile(r"^词表.*\.(txt|csv)$"),
]
# 成人主体源文件：文件名含「成人」的数据文件一律视为私有域内容。
ADULT_FILE = re.compile(r"成人.*\.(json|csv|txt)$", re.IGNORECASE)
PRIVATE_DIRS = {"私有域"}
PLACEHOLDER = re.compile(r"[<>{}\[\]]|YYYY|\*|\.\.\.|版本|示例")
PATH_REF = re.compile(r"`((?:apps|规范|使用|规则|工具|变更|记录)/[^`\n]+?)`")
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")


def load_words(path: str) -> list[str]:
    words = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            w = line.strip()
            if w and not w.startswith("#"):
                words.append(w)
    return words


def iter_files(root: str):
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for name in fn:
            yield os.path.join(dp, name)


def scan_words(root: str, words: list[str]) -> list[str]:
    hits = []
    for p in iter_files(root):
        rel = os.path.relpath(p, root)
        base = os.path.basename(p)
        for pat in FORBIDDEN_NAMES:
            if pat.match(base):
                hits.append(f"{rel}: 文件本身属维护侧元数据，不得入公开仓")
        if ADULT_FILE.search(base):
            hits.append(f"{rel}: 成人主体源文件属私有域，不得入公开仓（成人分类留在普通配置中即可）")
        if any(part in PRIVATE_DIRS for part in rel.split(os.sep)):
            hits.append(f"{rel}: 位于私有域目录，不得入公开仓")
        ext = os.path.splitext(p)[1].lower()
        if ext not in TEXT_EXT and os.path.basename(p) != ".gitignore":
            continue
        try:
            lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for w in words:
                if w in line:
                    hits.append(f"{rel}:{i}: 命中「{w}」 → {line.strip()[:100]}")
    return hits


def scan_dangling(root: str) -> list[str]:
    bad = []
    for p in iter_files(root):
        if not p.lower().endswith(".md"):
            continue
        rel = os.path.relpath(p, root)
        try:
            text = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for m in MD_LINK.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "#", "mailto:", "computer://")):
                continue
            clean = target.split("#")[0]
            if not clean or PLACEHOLDER.search(clean):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(p), clean))):
                bad.append(f"{rel}: 链接指向不存在 → {target}")
        for m in PATH_REF.finditer(text):
            ref = m.group(1)
            if PLACEHOLDER.search(ref):
                continue
            if not os.path.exists(os.path.join(root, ref)):
                bad.append(f"{rel}: 路径引用不存在 → {ref}")
    return bad


CAT_TIERS = ("极速", "快速", "标准", "慢速")


def scan_catmovie_names(root: str) -> list[str]:
    """小猫配置命名档位：只允许极速/快速/标准/慢速，或暂不写档位。"""
    p = os.path.join(root, "apps", "catmovie", "config.json")
    if not os.path.exists(p):
        return []
    try:
        data = json.load(open(p, encoding="utf-8-sig"))
    except Exception as e:
        return [f"apps/catmovie/config.json: 无法解析 → {e}"]
    bad = []
    for i, s in enumerate(data.get("sites", []), 1):
        name = str(s.get("name", ""))
        if "｜" not in name:
            continue
        tier = name.split("｜", 1)[0]
        if tier not in CAT_TIERS:
            bad.append(f"apps/catmovie/config.json: 第{i}条 {s.get('id', '')} "
                       f"名称档位「{tier or '空'}」非法，只允许 极速/快速/标准/慢速 或留空")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--词表", required=False, default=os.environ.get("SL_GATE_WORDS", ""))
    ap.add_argument("--根", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    ns = ap.parse_args()
    if not ns.词表 or not os.path.exists(ns.词表):
        print("缺少私有词表：请用 --词表 <路径> 或设置环境变量 SL_GATE_WORDS。")
        print("词表属私有域，不随仓库分发。")
        return 2
    words = load_words(ns.词表)
    hits = scan_words(ns.根, words)
    bad = scan_dangling(ns.根)
    names = scan_catmovie_names(ns.根)
    print(f"私有词表：{len(words)} 条；扫描根：{ns.根}")
    print(f"私有痕迹命中：{len(hits)}")
    for h in hits[:30]:
        print("  ✗", h)
    print(f"悬空引用：{len(bad)}")
    for b in bad[:30]:
        print("  ✗", b)
    print(f"命名档位非法：{len(names)}")
    for n in names[:30]:
        print("  ✗", n)
    if hits or bad or names:
        print("\n结论：阻断。公开仓不得出现私有内容痕迹、悬空引用或非法命名档位。")
        return 1
    print("\n结论：通过（私有痕迹 0，悬空引用 0，命名档位 0 非法）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
