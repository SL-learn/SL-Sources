"""跨应用源检测工具内核。

只做与具体应用无关的事：
- 严格 JSON 读取（BOM、重复键、SHA-256）；
- 条目/结果模型（域、成人标记、探活结论）；
- 报告落盘（JSON/CSV/Markdown），含探活、修复、补充、修复前后对比。

应用差异全部放在 adapters/<应用>.py 与 rules/<应用>.json，本文件不出现任何
阅读 / TVBox / 小猫 的字段名。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any


CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------- 数据模型

@dataclass
class Item:
    check_id: str
    level: str          # "错误" / "警告"
    message: str
    path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProbeResult:
    """单条探活结论。

    档位沿用规范口径：A/B/C/D；无法判定记 C 并写明原因。
    """
    state: str = "跳过"           # 通过 / 失败 / 跳过
    tier: str = "C"               # A / B / C / D
    elapsed_ms: int = 0
    message: str = ""
    endpoints: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "状态": self.state,
            "档位": self.tier,
            "耗时毫秒": self.elapsed_ms,
            "说明": self.message,
            "端点": self.endpoints,
        }


@dataclass
class EntryResult:
    file: str
    index: int
    name: str
    url: str
    source_type: Any
    domain: str = "公开"
    tags: list[str] = field(default_factory=list)
    errors: list[Item] = field(default_factory=list)
    warnings: list[Item] = field(default_factory=list)
    probe: ProbeResult | None = None
    checks_run: int = 0

    @property
    def status(self) -> str:
        if self.errors:
            return "不通过"
        if self.warnings:
            return "警告"
        return "通过"

    def add(self, check_id: str, level: str, message: str, path: str = "") -> None:
        item = Item(check_id, level, message, path)
        if level == "错误":
            self.errors.append(item)
        else:
            self.warnings.append(item)

    def tag(self, name: str) -> None:
        if name not in self.tags:
            self.tags.append(name)

    def to_dict(self) -> dict:
        return {
            "文件": self.file,
            "序号": self.index,
            "名称": self.name,
            "地址": self.url,
            "类型": self.source_type,
            "域": self.domain,
            "标记": self.tags,
            "状态": self.status,
            "错误数": len(self.errors),
            "警告数": len(self.warnings),
            "错误": [i.to_dict() for i in self.errors],
            "警告": [i.to_dict() for i in self.warnings],
            "探活": self.probe.to_dict() if self.probe else None,
        }


@dataclass
class LoadedJSON:
    path: str
    data: Any
    has_bom: bool
    duplicate_keys: list[str]
    size: int
    sha256: str


# ---------------------------------------------------------------- 读取

class DuplicateKeyRecorder:
    def __init__(self) -> None:
        self.duplicates: list[str] = []

    def hook(self, pairs):
        seen = {}
        for key, value in pairs:
            if key in seen:
                self.duplicates.append(key)
            seen[key] = value
        return seen


def load_json_strict(path: str) -> LoadedJSON:
    raw = open(path, "rb").read()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    recorder = DuplicateKeyRecorder()
    data = json.loads(text, object_pairs_hook=recorder.hook)
    digest = hashlib.sha256(raw).hexdigest().upper()
    return LoadedJSON(path, data, has_bom, recorder.duplicates, len(raw), digest)


def expand_inputs(paths: list[str]) -> list[str]:
    files: list[str] = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                for name in sorted(names):
                    if name.lower().endswith(".json"):
                        files.append(os.path.join(root, name))
        elif os.path.isfile(p):
            files.append(p)
        else:
            raise FileNotFoundError(p)
    return files


def file_sha256(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest().upper()


def now_text() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S%z")


def date_text() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


def stamp_text() -> str:
    return datetime.now(CST).strftime("%Y%m%d_%H%M%S")


def cn_num(n: int) -> str:
    """把 1–99 的整数转成中文小写数字，用于报告章节号。"""
    digits = "零一二三四五六七八九"
    if n < 10:
        return digits[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + digits[n % 10]
    return digits[n // 10] + "十" + (digits[n % 10] if n % 10 else "")


def renumber_headings(lines: list[str]) -> list[str]:
    """条件章节会让章节号跳号，写盘前按出现顺序连续重编号。"""
    counter = 0
    for i, line in enumerate(lines):
        if line.startswith("## ") and "、" in line[:9]:
            counter += 1
            lines[i] = re.sub(r"^## [一二三四五六七八九十百]+、",
                              f"## {cn_num(counter)}、", line)
    return lines


# ---------------------------------------------------------------- 汇总

def coverage_rows(adapter) -> list[dict]:
    rows = []
    for item in adapter.coverage():
        if len(item) >= 3:
            cid, desc, judge = item[0], item[1], item[2]
        else:
            cid, desc, judge = item[0], item[1], "自动"
        rows.append({"编号": cid, "名称": desc, "判定": judge})
    return rows


def build_payload(adapter, results: list[EntryResult], global_errors: list[dict],
                  inputs: list[str], elapsed_ms: int, domain: str,
                  probe_enabled: bool = False) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.status == "通过")
    warned = sum(1 for r in results if r.status == "警告")
    failed = sum(1 for r in results if r.status == "不通过")
    top_errors: dict[str, int] = {}
    top_warnings: dict[str, int] = {}
    tier_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "未探活": 0}
    adult_tagged = 0
    private_count = 0
    for r in results:
        for i in r.errors:
            top_errors[i.check_id] = top_errors.get(i.check_id, 0) + 1
        for i in r.warnings:
            top_warnings[i.check_id] = top_warnings.get(i.check_id, 0) + 1
        if r.probe:
            tier_counts[r.probe.tier] = tier_counts.get(r.probe.tier, 0) + 1
        else:
            tier_counts["未探活"] += 1
        if r.tags:
            adult_tagged += 1
        if r.domain == "私有":
            private_count += 1
    return {
        "工具": getattr(adapter, "tool_name", "源检测"),
        "应用": adapter.name,
        "套件": adapter.suite,
        "基线": adapter.baseline,
        "域": domain,
        "探活启用": probe_enabled,
        "生成时间": now_text(),
        "耗时毫秒": elapsed_ms,
        "输入": [{"路径": p, "SHA-256": file_sha256(p)} for p in inputs],
        "汇总": {
            "条目数": total,
            "通过": passed,
            "警告": warned,
            "不通过": failed,
            "错误项": sum(len(r.errors) for r in results),
            "警告项": sum(len(r.warnings) for r in results),
            "文件级错误": len(global_errors),
            "错误TOP": sorted(top_errors.items(), key=lambda kv: (-kv[1], kv[0])),
            "警告TOP": sorted(top_warnings.items(), key=lambda kv: (-kv[1], kv[0])),
            "成人域标记": adult_tagged,
            "私有域条目": private_count,
            "探活档位": tier_counts,
        },
        "检查项": coverage_rows(adapter),
        "文件级错误": global_errors,
        "条目": [r.to_dict() for r in results],
    }


# ---------------------------------------------------------------- 报告

def _mdcell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _write_repair_csv(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["类别", "编号", "文件", "序号", "名称", "路径", "原值", "新值",
                    "依据", "人工确认", "已执行"])
        for row in rows:
            w.writerow([row["类别"], row["编号"], row["文件"], row["序号"], row["名称"],
                        row["路径"], row["原值"], row["新值"], row["依据"],
                        "是" if row["人工确认"] else "否", "是" if row["已执行"] else "否"])


def write_reports(outdir: str, payload: dict, results: list[EntryResult],
                  report_name: str = "报告", stamp: str = "") -> dict[str, str]:
    os.makedirs(outdir, exist_ok=True)
    stamp = stamp or datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    paths: dict[str, str] = {}

    json_path = os.path.join(outdir, f"{report_name}_{stamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    paths["json"] = json_path

    csv_path = os.path.join(outdir, f"明细_{stamp}.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["文件", "序号", "名称", "地址", "域", "标记", "状态",
                    "检查项", "级别", "说明", "位置"])
        for r in results:
            tag_text = "、".join(r.tags)
            if r.status == "通过" and not r.tags:
                w.writerow([r.file, r.index, r.name, r.url, r.domain, tag_text,
                            r.status, "", "", "全部通过", ""])
                continue
            for item in r.errors + r.warnings:
                w.writerow([r.file, r.index, r.name, r.url, r.domain, tag_text,
                            r.status, item.check_id, item.level, item.message, item.path])
            if r.status == "通过" and r.tags:
                w.writerow([r.file, r.index, r.name, r.url, r.domain, tag_text,
                            r.status, "", "", "通过（含标记）", ""])
    paths["csv"] = csv_path

    repairs = payload.get("修复清单", [])
    if repairs:
        p = os.path.join(outdir, f"修复清单_{stamp}.csv")
        _write_repair_csv(p, repairs)
        paths["修复csv"] = p
    supplements = payload.get("补充清单", [])
    if supplements:
        p = os.path.join(outdir, f"补充清单_{stamp}.csv")
        _write_repair_csv(p, supplements)
        paths["补充csv"] = p

    md_path = os.path.join(outdir, f"{report_name}_{stamp}.md")
    s = payload["汇总"]
    lines = [
        f"# {payload['工具']}报告（{payload['生成时间']}）",
        "",
        f"- 应用：`{payload['应用']}`；套件：`{payload['套件']}`；基线：`{payload['基线']}`",
        f"- 域：**{payload['域']}**；探活：{'启用' if payload['探活启用'] else '未启用'}",
        f"- 输入文件：{len(payload['输入'])} 个；条目：{s['条目数']} 条",
        f"- 结果：通过 **{s['通过']}** / 警告 **{s['警告']}** / 不通过 **{s['不通过']}**",
        f"- 错误项 {s['错误项']} 个；警告项 {s['警告项']} 个；文件级错误 {s['文件级错误']} 个",
        f"- 成人域标记 {s['成人域标记']} 条；私有域条目 {s['私有域条目']} 条",
    ]
    if payload["探活启用"]:
        t = s["探活档位"]
        lines.append(f"- 探活档位：A **{t.get('A', 0)}** / B **{t.get('B', 0)}** / "
                     f"C **{t.get('C', 0)}** / D **{t.get('D', 0)}** / 未探活 {t.get('未探活', 0)}")

    lines += ["", "## 一、输入与按文件分布", "",
              "| 文件 | SHA-256 | 条目 | 通过 | 警告 | 不通过 |",
              "| --- | --- | --- | --- | --- | --- |"]
    dist: dict[str, dict[str, int]] = {}
    for r in results:
        d = dist.setdefault(r.file, {"条目": 0, "通过": 0, "警告": 0, "不通过": 0})
        d["条目"] += 1
        d[r.status] += 1
    for item in payload["输入"]:
        d = dist.get(item["路径"], {"条目": 0, "通过": 0, "警告": 0, "不通过": 0})
        lines.append(f"| {_mdcell(os.path.basename(item['路径']))} | {item['SHA-256']} | "
                     f"{d['条目']} | {d['通过']} | {d['警告']} | {d['不通过']} |")

    lines += ["", "## 二、错误项分布（按检查编号）", "", "| 检查编号 | 次数 |", "| --- | --- |"]
    if s["错误TOP"]:
        lines += [f"| {cid} | {n} |" for cid, n in s["错误TOP"]]
    else:
        lines.append("| （无） | 0 |")
    lines += ["", "## 三、警告项分布（按检查编号）", "", "| 检查编号 | 次数 |", "| --- | --- |"]
    if s["警告TOP"]:
        lines += [f"| {cid} | {n} |" for cid, n in s["警告TOP"]]
    else:
        lines.append("| （无） | 0 |")

    lines += ["", "## 四、文件级错误", ""]
    if payload["文件级错误"]:
        lines += ["| 文件 | 说明 |", "| --- | --- |"]
        lines += [f"| {_mdcell(os.path.basename(e['文件']))} | {_mdcell(e['说明'])} |"
                  for e in payload["文件级错误"]]
    else:
        lines.append("无。")

    probed = [r for r in results if r.probe]
    if probed:
        lines += ["", "## 五、探活结果", "",
                  "| 文件 | # | 名称 | 域 | 档位 | 耗时(ms) | 状态 | 说明 |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in probed:
            p = r.probe
            lines.append(f"| {_mdcell(os.path.basename(r.file))} | {r.index} | {_mdcell(r.name)} | "
                         f"{r.domain} | {p.tier} | {p.elapsed_ms} | {p.state} | {_mdcell(p.message)} |")
        lines += ["", "> 探活时长与档位按各应用规范口径判定；规则级解析未执行的端点会在说明中标注。"]
    if payload.get("全局探活"):
        lines += ["", "### 全局对象探活", "", "| 对象 | 状态 | 说明 |", "| --- | --- | --- |"]
        for item in payload["全局探活"]:
            lines.append(f"| {_mdcell(item.get('对象', ''))} | {_mdcell(item.get('状态', ''))} | "
                         f"{_mdcell(item.get('说明', ''))} |")

    tagged = [r for r in results if r.tags]
    if tagged:
        lines += ["", "## 六、成人域标记", "",
                  "| 文件 | # | 名称 | 域 | 标记 | 处置 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for r in tagged:
            action = "仅打标（私有域）" if r.domain == "私有" else "不通过（公开域）"
            lines.append(f"| {_mdcell(os.path.basename(r.file))} | {r.index} | {_mdcell(r.name)} | "
                         f"{r.domain} | {'、'.join(r.tags)} | {action} |")

    if repairs:
        lines += ["", "## 七、修复清单（原文 → 新值）", "",
                  "| 编号 | 文件 | # | 名称 | 路径 | 原值 | 新值 | 人工确认 | 已执行 |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for row in repairs:
            lines.append(f"| {row['编号']} | {_mdcell(os.path.basename(row['文件']))} | {row['序号']} | "
                         f"{_mdcell(row['名称'])} | {_mdcell(row['路径'])} | {_mdcell(row['原值'])} | "
                         f"{_mdcell(row['新值'])} | {'是' if row['人工确认'] else '否'} | "
                         f"{'是' if row['已执行'] else '否'} |")
    if supplements:
        lines += ["", "## 八、补充清单", "",
                  "| 编号 | 文件 | # | 名称 | 路径 | 原值 | 新值 | 人工确认 | 已执行 |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for row in supplements:
            lines.append(f"| {row['编号']} | {_mdcell(os.path.basename(row['文件']))} | {row['序号']} | "
                         f"{_mdcell(row['名称'])} | {_mdcell(row['路径'])} | {_mdcell(row['原值'])} | "
                         f"{_mdcell(row['新值'])} | {'是' if row['人工确认'] else '否'} | "
                         f"{'是' if row['已执行'] else '否'} |")
    unhandled = payload.get("未处理项", [])
    if unhandled:
        lines += ["", "## 九、未处理项与原因", "",
                  "| 文件 | # | 名称 | 问题 | 原因 | 建议 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for row in unhandled:
            lines.append(f"| {_mdcell(os.path.basename(row.get('文件', '')))} | {row.get('序号', '')} | "
                         f"{_mdcell(row.get('名称', ''))} | {_mdcell(row.get('问题', ''))} | "
                         f"{_mdcell(row.get('原因', ''))} | {_mdcell(row.get('建议', ''))} |")

    compare = payload.get("修复前后对比")
    if compare:
        lines += ["", "## 十、修复前后对比", "",
                  "| 阶段 | 条目 | 通过 | 警告 | 不通过 | 错误项 | 警告项 | 成人域标记 |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for stage in ("修复前", "修复后"):
            c = compare.get(stage, {})
            lines.append(f"| {stage} | {c.get('条目数', 0)} | {c.get('通过', 0)} | {c.get('警告', 0)} | "
                         f"{c.get('不通过', 0)} | {c.get('错误项', 0)} | {c.get('警告项', 0)} | "
                         f"{c.get('成人域标记', 0)} |")

    lines += ["", "## 十一、逐条结果", "",
              "| 文件 | # | 名称 | 域 | 状态 | 错误（编号：原因） | 警告（编号：原因） |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        errs = "；".join(f"{i.check_id}：{_mdcell(i.message)}" for i in r.errors) or "-"
        warns = "；".join(f"{i.check_id}：{_mdcell(i.message)}" for i in r.warnings) or "-"
        lines.append(f"| {_mdcell(os.path.basename(r.file))} | {r.index} | {_mdcell(r.name)} | "
                     f"{r.domain} | {r.status} | {errs} | {warns} |")

    lines += ["", "## 十二、检查项覆盖", "", "| 编号 | 检查内容 | 判定 |", "| --- | --- | --- |"]
    lines += [f"| {c['编号']} | {_mdcell(c['名称'])} | {c['判定']} |" for c in payload["检查项"]]
    lines += ["", "> 结构检查为静态判定；探活只覆盖可静态构造的端点，规则级解析未执行的项在探活说明中标注。"]
    renumber_headings(lines)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    paths["md"] = md_path
    return paths
