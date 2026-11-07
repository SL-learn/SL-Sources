"""源检测统一入口。

命令：
  检测  python main.py 检测 --应用 阅读 <输入...> [--域 私有] [--探活] [--采样 N]
  修复  python main.py 修复 --应用 TVBox <输入...> [--域 私有] [--执行] [--覆盖]
  补充  python main.py 补充 --应用 阅读 <输入...> [--执行]

输入可以是单个 JSON 文件或目录（递归收集 *.json）。
每次执行都会在 记录/<日期>/<应用>/ 下落检测报告、修复/补充清单与执行记录，
并向 记录/索引.csv 追加一行。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any

import adapters
from core import LoadedJSON, build_payload, expand_inputs, load_json_strict, write_reports
from record import RecordWriter
from repair import write_repaired


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))
RULES_DIR = os.path.join(REPO_ROOT, "规则")


def _rules_path(app: str, explicit: str) -> str:
    if explicit:
        return explicit
    _module, _cls, rule_name = adapters.resolve_app(app)
    return os.path.join(RULES_DIR, f"{rule_name}.json")


def _load_all(files: list[str]) -> tuple[list[LoadedJSON], list[dict]]:
    loaded: list[LoadedJSON] = []
    errors: list[dict] = []
    for path in files:
        try:
            loaded.append(load_json_strict(path))
        except Exception as e:
            errors.append({"文件": path, "说明": f"JSON 解析失败：{e}"})
    return loaded, errors


def _after_loaded(plan_data: dict[str, Any]) -> list[LoadedJSON]:
    out: list[LoadedJSON] = []
    for path, data in plan_data.items():
        text = json.dumps(data, ensure_ascii=False).encode("utf-8")
        out.append(LoadedJSON(path, data, False, [],
                              len(text), hashlib.sha256(text).hexdigest().upper()))
    return out


def _stats(results, global_errors: list[dict]) -> dict:
    return {
        "条目数": len(results),
        "通过": sum(1 for r in results if r.status == "通过"),
        "警告": sum(1 for r in results if r.status == "警告"),
        "不通过": sum(1 for r in results if r.status == "不通过"),
        "错误项": sum(len(r.errors) for r in results),
        "警告项": sum(len(r.warnings) for r in results),
        "成人域标记": sum(1 for r in results if r.tags),
        "文件级错误": len(global_errors),
    }


def _exit_code(results, global_errors: list[dict], implemented: bool = True) -> int:
    if not implemented:
        return 3
    if any(r.status == "不通过" for r in results):
        return 1
    if global_errors or any(r.status == "警告" for r in results):
        return 2
    return 0


def _print_summary(payload: dict, paths: dict, record: dict) -> None:
    s = payload["汇总"]
    print(f"[{payload['应用']}] 域={payload['域']} 条目={s['条目数']} "
          f"通过={s['通过']} 警告={s['警告']} 不通过={s['不通过']}")
    print(f"  错误项={s['错误项']} 警告项={s['警告项']} 文件级={s['文件级错误']} "
          f"成人标记={s['成人域标记']}")
    if payload.get("探活启用"):
        t = s["探活档位"]
        print(f"  探活 A={t.get('A', 0)} B={t.get('B', 0)} C={t.get('C', 0)} "
              f"D={t.get('D', 0)} 未探活={t.get('未探活', 0)}")
    if payload.get("修复清单"):
        print(f"  修复 {len(payload['修复清单'])} 条（已执行 "
              f"{sum(1 for r in payload['修复清单'] if r['已执行'])} 条）")
    if payload.get("补充清单"):
        print(f"  补充 {len(payload['补充清单'])} 条（已执行 "
              f"{sum(1 for r in payload['补充清单'] if r['已执行'])} 条）")
    if payload.get("未处理项"):
        print(f"  未处理 {len(payload['未处理项'])} 条（见报告第九节）")
    print(f"  报告：{paths.get('md', '')}")
    print(f"  记录：{record.get('md', '')}")
    print(f"  索引：{record.get('index', '')}")


def cmd_detect(ns) -> int:
    adapter, rules, domain = _prepare(ns)
    files = expand_inputs(ns.输入)
    loaded, load_errors = _load_all(files)
    started = time.perf_counter()

    results, global_errors = adapter.validate_loaded(loaded)
    global_errors = load_errors + global_errors

    if getattr(ns, "清单", "") and hasattr(adapter, "validate_manifest"):
        if not getattr(ns, "源文件", ""):
            print("--清单 需要同时提供 --源文件", file=sys.stderr)
            return 3
        global_errors += adapter.validate_manifest(ns.清单, ns.源文件)

    global_probe: list[dict] = []
    if getattr(ns, "探活", False) and adapter.implemented:
        global_probe = adapter.probe(loaded, results, getattr(ns, "采样", 0))

    elapsed = int((time.perf_counter() - started) * 1000)
    payload = build_payload(adapter, results, global_errors, files, elapsed, domain,
                            probe_enabled=bool(getattr(ns, "探活", False)))
    payload["全局探活"] = global_probe
    payload["修复清单"] = []
    payload["补充清单"] = []
    payload["未处理项"] = []

    writer = RecordWriter(ns.记录, getattr(adapter, "record_app", adapter.name))
    outdir = ns.输出 or writer.dir
    prefix = getattr(adapter, "report_prefix", "") or ""
    paths = write_reports(outdir, payload, results, prefix + "检测报告", writer.stamp)
    code = _exit_code(results, global_errors, adapter.implemented)
    record = writer.write(
        "main.py " + " ".join(sys.argv[1:]), domain, payload, paths,
        [], [], [], elapsed, code,
        note="修复/补充未执行" if ns.命令 == "检测" else "")
    _print_summary(payload, paths, record)
    return code


def _prepare(ns):
    rule_path = _rules_path(ns.应用, getattr(ns, "规则", ""))
    if not os.path.isfile(rule_path):
        print(f"规则文件不存在：{rule_path}", file=sys.stderr)
        sys.exit(3)
    rules = json.load(open(rule_path, "r", encoding="utf-8-sig"))
    domain = getattr(ns, "域", "") or rules.get("域", {}).get("默认", "公开")
    allowed = rules.get("域", {}).get("取值", {})
    if domain not in allowed:
        print(f"域只允许 {'、'.join(allowed)}，实际 {domain}", file=sys.stderr)
        sys.exit(3)
    adapter = adapters.create_adapter(ns.应用, rules, domain)
    adapter.suite = rules.get("suite", adapter.suite)
    adapter.baseline = rules.get("baseline", adapter.baseline)
    return adapter, rules, domain


def cmd_fix(ns) -> int:
    adapter, rules, domain = _prepare(ns)
    files = expand_inputs(ns.输入)
    loaded, load_errors = _load_all(files)
    if not loaded:
        print("没有可读取的 JSON 输入", file=sys.stderr)
        return 3

    do_supplement = ns.命令 == "补充" or getattr(ns, "含补充", False)
    writer = RecordWriter(ns.记录, getattr(adapter, "record_app", adapter.name))
    started = time.perf_counter()
    plan = adapter.build_plan(loaded, do_repair=(ns.命令 == "修复"),
                              do_supplement=do_supplement)

    before_results, before_errors = adapter.validate_loaded(loaded)
    before_errors = load_errors + before_errors
    after_loaded = _after_loaded(plan.data)
    after_results, after_errors = adapter.validate_loaded(after_loaded)

    executed = bool(getattr(ns, "执行", False))
    wrote: dict = {}
    if executed:
        plan.mark_applied()
        wrote = write_repaired(
            plan,
            outdir=os.path.join(writer.dir, "修复结果"),
            backup_dir=os.path.join(writer.dir, "备份"),
            stamp=writer.stamp,
            overwrite=bool(getattr(ns, "覆盖", False)))

    elapsed = int((time.perf_counter() - started) * 1000)
    payload = build_payload(adapter, after_results, after_errors, files, elapsed, domain,
                            probe_enabled=False)
    payload["修复清单"] = plan.repairs()
    payload["补充清单"] = plan.supplements()
    payload["未处理项"] = plan.unhandled
    payload["修复前后对比"] = {
        "修复前": _stats(before_results, before_errors),
        "修复后": _stats(after_results, after_errors),
    }
    payload["全局探活"] = []
    if wrote:
        payload["落盘"] = wrote

    outdir = ns.输出 or writer.dir
    label = "修复报告" if ns.命令 == "修复" else "补充报告"
    paths = write_reports(outdir, payload, after_results,
                          (getattr(adapter, "report_prefix", "") or "") + label,
                          writer.stamp)
    code = _exit_code(after_results, after_errors, adapter.implemented)
    mode = "已执行" if executed else "dry-run（未写任何输入文件）"
    note = f"{mode}；检测统计为修复后，修复前见对比表"
    if wrote:
        note += f"；新文件 {len(wrote['written'])} 个，备份 {len(wrote['backups'])} 个，diff：{wrote['diff']}"
    record = writer.write("main.py " + " ".join(sys.argv[1:]), domain, payload, paths,
                          plan.repairs(), plan.supplements(), plan.unhandled,
                          elapsed, code, note=note)
    _print_summary(payload, paths, record)
    return code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="跨应用源检测：阅读 / TVBox / 小猫影视")
    sub = p.add_subparsers(dest="命令", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--应用", required=True, choices=adapters.APP_NAMES)
        sp.add_argument("输入", nargs="+", help="JSON 文件或目录")
        sp.add_argument("--域", default="", choices=["公开", "私有"],
                        help="公开=成人内容阻断；私有=只打标;缺省取规则里的默认域")
        sp.add_argument("--规则", default="", help="规则 JSON 路径，缺省 规则/<应用>.json")
        sp.add_argument("--输出", default="", help="报告输出目录，缺省 工具/源检测/记录/<日期>/<应用>/")
        sp.add_argument("--记录", default=os.path.join(BASE_DIR, "记录"), help="记录根目录（本地，不入公开仓）")

    det = sub.add_parser("检测", help="只做结构检查，可选探活")
    common(det)
    det.add_argument("--探活", action="store_true", help="启用网络探活（按应用规范口径）")
    det.add_argument("--采样", type=int, default=0, help="探活采样上限，缺省取规则配置")
    det.add_argument("--清单", default="", help="阅读发布清单 JSON（RBS-PRC-039）")
    det.add_argument("--源文件", default="", help="清单对应的书源文件，用于核对 sha256/entries")
    det.set_defaults(func=cmd_detect)

    fix = sub.add_parser("修复", help="确定性修复，默认 dry-run")
    common(fix)
    fix.add_argument("--执行", action="store_true", help="落盘修复结果（写新文件+备份+diff）")
    fix.add_argument("--覆盖", action="store_true", help="覆盖原文件（覆盖前先备份，可用备份回滚）")
    fix.add_argument("--含补充", action="store_true", help="修复同时执行补充")
    fix.set_defaults(func=cmd_fix)

    sup = sub.add_parser("补充", help="补齐可推断的缺失项，默认 dry-run")
    common(sup)
    sup.add_argument("--执行", action="store_true", help="落盘补充结果（写新文件+备份+diff）")
    sup.add_argument("--覆盖", action="store_true", help="覆盖原文件（覆盖前先备份）")
    sup.set_defaults(func=cmd_fix)
    return p


def main() -> int:
    parser = build_parser()
    ns = parser.parse_args()
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
