"""公开仓扫描门禁：查私有痕迹 + 查悬空引用。

用法（仓库根执行）：
    python 工具/公开仓扫描/扫描.py --词表 <私有域词表路径>
    python 工具/公开仓扫描/扫描.py --词表 ... --根 <被测目录>

退出码：0 通过；1 有命中。
词表属私有域，**不入公开仓**；脚本里不内置任何私有词。
"""
from __future__ import annotations

import argparse
import os
import re
import sys

TEXT_EXT = {".md", ".txt", ".csv", ".json", ".py", ".gitignore", ".yml", ".yaml"}
SKIP_DIRS = {".git", "__pycache__", "_分析", "备份", ".idea", ".vscode"}
FORBIDDEN_NAMES = [
    re.compile(r".*清单\.csv$"),
    re.compile(r"^站点目录.*\.(json|csv)$"),
    re.compile(r"^探活明细.*"),
]
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
        for pat in FORBIDDEN_NAMES:
            if pat.match(os.path.basename(p)):
                hits.append(f"{rel}: 文件本身属维护侧清单，不得入公开仓")
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
    print(f"私有词表：{len(words)} 条；扫描根：{ns.根}")
    print(f"私有痕迹命中：{len(hits)}")
    for h in hits[:30]:
        print("  ✗", h)
    print(f"悬空引用：{len(bad)}")
    for b in bad[:30]:
        print("  ✗", b)
    if hits or bad:
        print("\n结论：阻断。公开仓不得出现私有内容痕迹或悬空引用。")
        return 1
    print("\n结论：通过（私有痕迹 0，悬空引用 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
