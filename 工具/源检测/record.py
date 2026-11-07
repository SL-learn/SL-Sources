"""执行记录落盘。

目录固定：记录/<yyyyMMdd>/<应用>/，每次执行三件套同名不同后缀：
- 执行记录_<时间戳>.json：机器可读；
- 执行记录_<时间戳>.md：人读；
- 同目录下的检测报告（由 core.write_reports 写入）。

另维护 记录/索引.csv，累积可追溯。
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime

from core import CST, date_text, stamp_text, now_text, renumber_headings


INDEX_HEADER = ["时间", "应用", "域", "命令", "输入数", "条目数", "通过", "警告", "不通过",
                "成人域标记", "修复条数", "补充条数", "未处理条数", "探活A", "探活B",
                "探活C", "探活D", "耗时毫秒", "退出码", "记录目录"]


class RecordWriter:
    def __init__(self, base_dir: str, app: str) -> None:
        self.base_dir = base_dir
        self.app = app
        self.day = date_text()
        self.dir = os.path.join(base_dir, self.day, app)
        base = stamp_text()
        self.stamp = base
        n = 1
        while os.path.exists(os.path.join(self.dir, f"执行记录_{self.stamp}.json")):
            n += 1
            self.stamp = f"{base}_{n}"

    def _append_index(self, row: dict) -> str:
        path = os.path.join(self.base_dir, "索引.csv")
        exists = os.path.isfile(path)
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(INDEX_HEADER)
            w.writerow([row.get(k, "") for k in INDEX_HEADER])
        return path

    def write(self, command: str, domain: str, payload: dict, report_paths: dict,
              repairs: list[dict], supplements: list[dict], unhandled: list[dict],
              elapsed_ms: int, exit_code: int, note: str = "") -> dict:
        os.makedirs(self.dir, exist_ok=True)
        s = payload["汇总"]
        t = s.get("探活档位", {})

        record = {
            "时间": now_text(),
            "应用": self.app,
            "域": domain,
            "命令": command,
            "输入清单": [{"路径": i["路径"], "SHA-256": i["SHA-256"]} for i in payload["输入"]],
            "检测统计": {
                "条目数": s["条目数"], "通过": s["通过"], "警告": s["警告"],
                "不通过": s["不通过"], "错误项": s["错误项"], "警告项": s["警告项"],
                "文件级错误": s["文件级错误"], "成人域标记": s["成人域标记"],
                "探活档位": t,
            },
            "修复清单": repairs,
            "补充清单": supplements,
            "未处理项": unhandled,
            "修复前后对比": payload.get("修复前后对比"),
            "全局探活": payload.get("全局探活", []),
            "报告": report_paths,
            "耗时毫秒": elapsed_ms,
            "退出码": exit_code,
            "备注": note,
        }
        json_path = os.path.join(self.dir, f"执行记录_{self.stamp}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        md_path = os.path.join(self.dir, f"执行记录_{self.stamp}.md")
        lines = [
            f"# 源检测执行记录（{record['时间']}）",
            "",
            f"- 应用：`{self.app}`；域：**{domain}**；退出码：{exit_code}",
            f"- 命令：`{command}`",
            f"- 耗时：{elapsed_ms} ms",
            f"- 输入：{len(record['输入清单'])} 个文件",
            "",
            "## 一、输入清单",
            "",
            "| 文件 | SHA-256 |",
            "| --- | --- |",
        ]
        lines += [f"| {i['路径']} | {i['SHA-256']} |" for i in record["输入清单"]]
        lines += ["", "## 二、检测统计", "",
                  f"- 条目 {s['条目数']}：通过 {s['通过']} / 警告 {s['警告']} / 不通过 {s['不通过']}",
                  f"- 错误项 {s['错误项']}；警告项 {s['警告项']}；文件级错误 {s['文件级错误']}",
                  f"- 成人域标记 {s['成人域标记']}；探活档位 "
                  f"A {t.get('A', 0)} / B {t.get('B', 0)} / C {t.get('C', 0)} / D {t.get('D', 0)}"]
        if repairs:
            lines += ["", "## 三、修复清单（原文 → 新值）", "",
                      "| 编号 | 文件 | # | 路径 | 原值 | 新值 | 依据 | 人工确认 | 已执行 |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
            lines += [f"| {r['编号']} | {os.path.basename(r['文件'])} | {r['序号']} | {r['路径']} | "
                      f"{r['原值']} | {r['新值']} | {r['依据']} | "
                      f"{'是' if r['人工确认'] else '否'} | {'是' if r['已执行'] else '否'} |"
                      for r in repairs]
        if supplements:
            lines += ["", "## 四、补充清单", "",
                      "| 编号 | 文件 | # | 路径 | 原值 | 新值 | 依据 | 人工确认 | 已执行 |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
            lines += [f"| {r['编号']} | {os.path.basename(r['文件'])} | {r['序号']} | {r['路径']} | "
                      f"{r['原值']} | {r['新值']} | {r['依据']} | "
                      f"{'是' if r['人工确认'] else '否'} | {'是' if r['已执行'] else '否'} |"
                      for r in supplements]
        if unhandled:
            lines += ["", "## 五、未处理项与原因", "",
                      "| 文件 | # | 问题 | 原因 | 建议 |", "| --- | --- | --- | --- | --- |"]
            lines += [f"| {os.path.basename(r['文件'])} | {r['序号']} | {r['问题']} | "
                      f"{r['原因']} | {r['建议']} |" for r in unhandled]
        compare = record["修复前后对比"]
        if compare:
            lines += ["", "## 六、修复前后对比", "",
                      "| 阶段 | 条目 | 通过 | 警告 | 不通过 | 错误项 | 警告项 | 成人域标记 |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for stage in ("修复前", "修复后"):
                c = compare.get(stage, {})
                lines.append(f"| {stage} | {c.get('条目数', 0)} | {c.get('通过', 0)} | "
                             f"{c.get('警告', 0)} | {c.get('不通过', 0)} | {c.get('错误项', 0)} | "
                             f"{c.get('警告项', 0)} | {c.get('成人域标记', 0)} |")
        if record["全局探活"]:
            lines += ["", "## 七、全局对象探活", "", "| 对象 | 状态 | 说明 |", "| --- | --- | --- |"]
            lines += [f"| {g['对象']} | {g['状态']} | {g['说明']} |" for g in record["全局探活"]]
        lines += ["", "## 八、报告文件", ""]
        lines += [f"- {k}：{v}" for k, v in report_paths.items()]
        if note:
            lines += ["", f"> {note}"]
        renumber_headings(lines)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        index_path = self._append_index({
            "时间": record["时间"], "应用": self.app, "域": domain, "命令": command,
            "输入数": len(record["输入清单"]), "条目数": s["条目数"],
            "通过": s["通过"], "警告": s["警告"], "不通过": s["不通过"],
            "成人域标记": s["成人域标记"], "修复条数": len(repairs),
            "补充条数": len(supplements), "未处理条数": len(unhandled),
            "探活A": t.get("A", 0), "探活B": t.get("B", 0),
            "探活C": t.get("C", 0), "探活D": t.get("D", 0),
            "耗时毫秒": elapsed_ms, "退出码": exit_code, "记录目录": self.dir,
        })
        return {"json": json_path, "md": md_path, "index": index_path, "dir": self.dir}
