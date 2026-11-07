"""确定性修复与补充的执行框架。

职责：
- 承载「修复项 / 补充项 / 未处理项」三类留痕记录；
- 提供 JSON 原地改写、备份、diff、落盘；
- 不判断业务规则，具体判定由 adapters 调用 `RepairPlan.add()` 写入。

约束：
- 只接受能确定性判定的改动；涉及内容取舍的一律走 `RepairPlan.unhandle()`；
- 未执行（dry-run）时只改内存副本，不写输入文件；
- 执行时先把原文件复制到备份目录，再写新值，保证可回滚。
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any


def _text(value: Any) -> str:
    if value is _MISSING:
        return "<缺失>"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


_MISSING = object()


@dataclass
class Change:
    code: str                 # F-xx / S-xx
    kind: str                 # "修复" / "补充"
    file: str
    index: int
    name: str
    path: str                 # bookSourceName / sites[3].key / ruleSearch.checkKeyWord
    old: Any
    new: Any
    reason: str
    need_confirm: bool = False
    applied: bool = False

    def to_row(self) -> dict:
        return {
            "类别": self.kind,
            "编号": self.code,
            "文件": self.file,
            "序号": self.index,
            "名称": self.name,
            "路径": self.path,
            "原值": _text(self.old),
            "新值": _text(self.new),
            "依据": self.reason,
            "人工确认": self.need_confirm,
            "已执行": self.applied,
        }


@dataclass
class RepairPlan:
    data: dict[str, Any] = field(default_factory=dict)
    original: dict[str, Any] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    unhandled: list[dict] = field(default_factory=list)

    def add(self, code: str, kind: str, file: str, index: int, name: str, path: str,
            old: Any, new: Any, reason: str, need_confirm: bool = False) -> None:
        if old == new:
            return
        self.changes.append(Change(code, kind, file, index, name, path, old, new,
                                   reason, need_confirm))

    def unhandle(self, file: str, index: int, name: str, problem: str,
                 reason: str, advice: str = "") -> None:
        self.unhandled.append({"文件": file, "序号": index, "名称": name,
                               "问题": problem, "原因": reason, "建议": advice})

    def repairs(self) -> list[dict]:
        return [c.to_row() for c in self.changes if c.kind == "修复"]

    def supplements(self) -> list[dict]:
        return [c.to_row() for c in self.changes if c.kind == "补充"]

    def mark_applied(self) -> None:
        for c in self.changes:
            c.applied = True

    def changed_files(self) -> list[str]:
        return sorted({c.file for c in self.changes})


def snapshot(data_by_file: dict[str, Any]) -> dict[str, Any]:
    return {p: copy.deepcopy(d) for p, d in data_by_file.items()}


def write_repaired(plan: RepairPlan, outdir: str, backup_dir: str,
                   stamp: str, overwrite: bool = False) -> dict:
    """落盘修复结果。

    overwrite=False：新文件写到 outdir，原文件只做备份；
    overwrite=True：覆盖原文件，但在覆盖前先备份到 backup_dir。
    """
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(backup_dir, exist_ok=True)
    written: list[str] = []
    backups: list[str] = []
    diff_parts: list[str] = []

    for path in plan.changed_files():
        new_data = plan.data[path]
        old_data = plan.original[path]
        base = os.path.basename(path)

        backup_path = os.path.join(backup_dir, f"{base}.{stamp}.bak")
        shutil.copy2(path, backup_path)
        backups.append(backup_path)

        target = path if overwrite else os.path.join(outdir, base)
        if not overwrite and os.path.abspath(target) == os.path.abspath(path):
            target = os.path.join(outdir, f"{os.path.splitext(base)[0]}_修复{os.path.splitext(base)[1]}")
        with open(target, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        written.append(target)

        old_lines = json.dumps(old_data, ensure_ascii=False, indent=2).splitlines(keepends=True)
        new_lines = json.dumps(new_data, ensure_ascii=False, indent=2).splitlines(keepends=True)
        diff_parts.append(f"# 文件：{base}\n")
        diff_parts.extend(difflib.unified_diff(old_lines, new_lines, fromfile=f"{base}(原)",
                                               tofile=f"{base}(修复后)", n=2))

    diff_path = ""
    if diff_parts:
        diff_path = os.path.join(outdir, f"修复对比_{stamp}.diff")
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write("".join(diff_parts))
    return {"written": written, "backups": backups, "diff": diff_path}


def rollback_rows(backups: list[str], written: list[str]) -> list[str]:
    """把备份复制回被覆盖的目标，供 main 在 `--覆盖` 失败或用户要求回滚时调用。"""
    actions: list[str] = []
    for backup, target in zip(backups, written):
        if os.path.isfile(backup):
            shutil.copy2(backup, target)
            actions.append(f"{backup} -> {target}")
    return actions
