# -*- coding: utf-8 -*-
"""条款编号校验。

四项检查：
1. 所有规范文档中的新编号全局唯一；
2. 规范条款与 规则/*.json 一一对应（规则无 ID 字段则跳过并说明）；
3. 规范/使用/工具/变更/规则/apps 下的引用都能解析到已定义编号；
4. 每个（应用, 类别）段内序号连续，无空号。

用法：python 工具/编号校验/校验.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "规范"
USE_DIR = ROOT / "使用"
RULES_DIR = ROOT / "规则"
SCAN_DIRS = ["规范", "使用", "工具", "变更", "规则", "apps"]
TEXT_EXT = {".md", ".txt", ".py", ".json", ".csv", ".yaml", ".yml"}
SKIP_DIR_NAMES = {"__pycache__", ".git"}

APP = r"(?:TVB|CAT|RBS|RRS|SYS|DOC)"
CAT = r"(?:NAM|STR|CFG|CLS|PRB|VER|DIST|SEC|PRC|DOC)"
DEF_TABLE = re.compile(r"^\|\s*(" + APP + "-" + CAT + r"-\d{3})\s*\|")
DEF_BOLD = re.compile(r"^\*\*(" + APP + "-" + CAT + r"-\d{3})[【\[]")
ID_RE = re.compile(r"(?<![A-Za-z0-9_-])(" + APP + "-" + CAT + r"-\d{3})(?![0-9])")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def iter_files(top: Path):
    if not top.exists():
        return
    for p in sorted(top.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT_EXT:
            if any(part in SKIP_DIR_NAMES for part in p.parts):
                continue
            yield p


def collect_definitions() -> tuple[dict[str, list[str]], list[str]]:
    """返回 {编号: [定义位置]} 与按文档顺序的定义列表。

    条款定义分布在 规范/（各应用正本）与 使用/（TVBox 分发条款 TVB-DIST 段的正文）。
    """
    found: dict[str, list[str]] = {}
    order: list[str] = []
    files = sorted(SPEC_DIR.glob("*.md")) + sorted(USE_DIR.glob("*.md"))
    for p in files:
        for i, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
            m = DEF_TABLE.match(line) or DEF_BOLD.match(line)
            if not m:
                continue
            fid = m.group(1)
            found.setdefault(fid, []).append(f"{rel(p)}:{i}")
            order.append(fid)
    return found, order


def has_id_field(value) -> bool:
    keys = {"id", "编号", "条款号", "条款编号", "clauseid", "ruleid"}
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k).lower() in keys and isinstance(v, str) and ID_RE.fullmatch(v.strip()):
                return True
            if has_id_field(v):
                return True
    elif isinstance(value, list):
        return any(has_id_field(v) for v in value)
    return False


def main() -> int:
    print("== 条款编号校验 ==")
    print(f"仓库根：{ROOT}")

    defined, order = collect_definitions()
    ids = set(defined)

    # 1. 唯一性
    dups = {k: v for k, v in defined.items() if len(v) > 1}
    print(f"\n[1/4] 编号唯一性：定义 {len(order)} 条 / 去重 {len(ids)} 个")
    if dups:
        print(f"      重复 {len(dups)} 个：")
        for k, v in sorted(dups.items()):
            print(f"        - {k}: {', '.join(v)}")
    else:
        print("      重复 0")

    # 2. 规则 JSON 对应
    print("\n[2/4] 规范条款 ↔ 规则/*.json")
    rule_files = sorted(RULES_DIR.glob("*.json")) if RULES_DIR.exists() else []
    skipped = []
    if not rule_files:
        print("      规则目录不存在或为空，跳过")
    for p in rule_files:
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception as e:  # noqa: BLE001
            print(f"      {rel(p)}：解析失败 {e}")
            continue
        if not has_id_field(data):
            skipped.append(p)
            print(f"      {rel(p)}：无 ID 字段，跳过该项")
            continue
        rule_ids = set(ID_RE.findall(p.read_text(encoding="utf-8-sig")))
        unknown = sorted(rule_ids - ids)
        missing = sorted(ids - rule_ids)
        print(f"      {rel(p)}：规则引用 {len(rule_ids)} 个，未定义 {len(unknown)} 个，"
              f"未覆盖条款 {len(missing)} 个")
        for x in unknown:
            print(f"        - 有规则无条款：{x}")
    if rule_files and len(skipped) == len(rule_files):
        print("      结论：规则文件均无条款 ID 字段，本项按设计跳过（规则以字段名与判据表达，不写编号）")

    # 3. 引用解析
    print("\n[3/4] 引用解析")
    dangling: list[tuple[str, int, str]] = []
    scanned_files = 0
    ref_count = 0
    for name in SCAN_DIRS:
        for p in iter_files(ROOT / name):
            scanned_files += 1
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            for i, line in enumerate(text.split("\n"), 1):
                for m in ID_RE.finditer(line):
                    ref_count += 1
                    if m.group(1) not in ids:
                        dangling.append((rel(p), i, m.group(1)))
    print(f"      扫描 {scanned_files} 个文件 / {ref_count} 处编号引用")
    if dangling:
        print(f"      悬空引用 {len(dangling)} 处：")
        for f, i, fid in dangling:
            print(f"        - {f}:{i} {fid}")
    else:
        print("      悬空引用 0")

    # 4. 空号
    print("\n[4/4] 空号检查")
    segments: dict[tuple[str, str], list[int]] = {}
    for fid in order:
        app, cat, num = fid.split("-")
        segments.setdefault((app, cat), []).append(int(num))
    gaps = []
    for (app, cat), nums in sorted(segments.items()):
        uniq = sorted(set(nums))
        missing = [n for n in range(1, max(uniq) + 1) if n not in uniq]
        if missing:
            gaps.append((app, cat, missing))
    print(f"      共 {len(segments)} 个（应用, 类别）段")
    if gaps:
        for app, cat, missing in gaps:
            print(f"        - {app}-{cat}: 空号 {missing}")
    else:
        print("      空号 0")
    detail = "、".join(f"{a}-{c}:{max(v)}" for (a, c), v in sorted(segments.items()))
    print(f"      段明细（末号）：{detail}")

    ok = not dups and not dangling and not gaps
    print("\n结论：" + ("通过" if ok else "不通过") +
          f"（重复 {len(dups)} / 悬空 {len(dangling)} / 空号 {len(gaps)}）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
