"""小猫影视适配器占位。

规范已到 v1.5（《小猫影视 自建源统一规格规范》），但样板线路尚未落地，
本轮只保留接口与检查计划，不接入真实判定。接入时按下列钩子实现：
- validate_loaded / probe / build_plan；
- rules/小猫影视.json 的检查项、修复/补充动作、探活参数。

注意：小猫规范 v1.1 写明「成人源完全不发布」，与本工具的「公开阻断/私有打标」
通用口径不同，接入前需要用户拍板用哪一套。
"""

from __future__ import annotations

import copy
import json

from core import EntryResult, LoadedJSON, ProbeResult
from repair import RepairPlan


class CatmovieAdapter:
    name = "小猫影视"
    tool_name = "源检测·小猫影视"
    suite = "小猫P0（占位）"
    baseline = "小猫影视 自建源统一规格规范 v1.5"
    implemented = False

    def __init__(self, rules: dict, domain: str = ""):
        self.cfg = rules
        self.domain = domain or rules.get("域", {}).get("默认", "公开")
        self.adult_mode = rules.get("域", {}).get("取值", {}).get(self.domain, "阻断")

    def coverage(self) -> list[tuple[str, str, str]]:
        return [
            ("T-01", "JSON 可解析、顶层对象、无 BOM、无重复键（CAT-PRC-011）", "待接入"),
            ("T-02", "顶层字段白名单与 8 字段结构（CAT-CFG-016）", "待接入"),
            ("T-03", "id 字符集/长度/唯一（CAT-NAM-005/CAT-NAM-006）", "待接入"),
            ("T-04", "name 速度档位｜站点中文名格式（CAT-NAM-008/CAT-NAM-009）", "待接入"),
            ("T-05", "type 0/1 与 api 形态（maccms/JS，CAT-CFG-014/CAT-CFG-015）", "待接入"),
            ("T-06", "extra.category 等 JSON 字符串字段（CAT-CFG-023）", "待接入"),
            ("T-07", "lives[] 分组名与 type（CAT-NAM-010、TVB-CFG-012 对应条款）", "待接入"),
            ("T-08", "成人内容识别与打标：按应用域配置执行（CAT-SEC-001/CAT-SEC-003）", "待接入"),
            ("T-09", "自造字段与禁用模板 t4（CAT-CFG-016、CAT-CFG-026）", "待接入"),
            ("T-10", "探活：maccms 3 端点 / JS 契约 / 直播列表（CAT-PRB-001~CAT-PRB-008）", "待接入"),
        ]

    def validate(self, files: list[str]) -> tuple[list[EntryResult], list[dict]]:
        return self.validate_loaded([])

    def validate_loaded(self, loaded: list[LoadedJSON]) -> tuple[list[EntryResult], list[dict]]:
        errors = [{"文件": path, "说明": "小猫影视适配器为占位实现，未执行任何检查；等样板线路落地后接入"}
                  for path in ([lj.path for lj in loaded] or ["（未提供输入）"])]
        return [], errors

    def probe(self, loaded: list[LoadedJSON], results: list[EntryResult],
              limit: int = 0) -> list[dict]:
        return []

    def build_plan(self, loaded: list[LoadedJSON], do_repair: bool = True,
                   do_supplement: bool = True) -> RepairPlan:
        plan = RepairPlan()
        plan.original = {lj.path: copy.deepcopy(lj.data) for lj in loaded}
        plan.data = {lj.path: copy.deepcopy(lj.data) for lj in loaded}
        for lj in loaded:
            plan.unhandle(lj.path, -1, "-", "小猫影视适配器未实现",
                          "样板线路尚未落地，接口已预留", "等样板线路出来后接入 rules/小猫影视.json")
        return plan


def load_rules(path: str) -> dict:
    return json.load(open(path, "r", encoding="utf-8-sig"))
