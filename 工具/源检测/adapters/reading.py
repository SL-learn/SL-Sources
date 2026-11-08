"""阅读（Legado 3.x）书源适配器。

检查项对应《阅读书源统一规格规范》§13.2 与 §10；修复/补充只做确定性动作。
T-09 按 rules 的「域」开关执行：
- 公开域命中 → 错误（不通过）；
- 私有域命中 → 警告 + 标记「成人域」，不阻断。
"""

from __future__ import annotations

import base64
import copy
import json
import os
import re
import urllib.parse
from typing import Any

from core import EntryResult, LoadedJSON, ProbeResult, load_json_strict
from repair import RepairPlan, _MISSING
import probe as probe_api


def _compile(pattern: str) -> tuple[bool, str]:
    try:
        re.compile(pattern)
        return True, ""
    except re.error as e:
        return False, str(e)


def _java_only(pattern: str) -> bool:
    return any(token in pattern for token in (r"\p{", r"\z", r"\G", r"\Q"))


def _balanced(text: str) -> str:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    quote = ""
    esc = False
    for ch in text:
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack[-1] != pairs[ch]:
                return f"括号不配对：多余的 {ch}"
            stack.pop()
    if quote:
        return "字符串引号未闭合"
    if stack:
        return f"括号未闭合：{''.join(stack)}"
    return ""


def _regex_compile_check(raw: str) -> str:
    pattern = raw.strip()
    if pattern.startswith("/") and pattern.rfind("/") > 0:
        last = pattern.rfind("/")
        pattern = pattern[1:last]
    ok, err = _compile(pattern)
    if ok or _java_only(pattern):
        return ""
    return f"正则无法编译：{err}"


def _mask_value(value: str) -> str:
    def blank(m: re.Match) -> str:
        return " " * len(m.group(0))

    masked = re.sub(r"\{\{[\s\S]*?\}\}", blank, value)
    masked = re.sub(r"<js>[\s\S]*?</js>", blank, masked, flags=re.I)
    return masked


def check_rule_syntax(value: Any, field: str, is_list: bool) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    if not isinstance(value, str) or not value:
        return problems
    if value.count("{{") != value.count("}}"):
        problems.append(("错误", "{{ }} 未配对"))

    stripped = value.strip()
    lower = stripped.lower()
    masked = _mask_value(value).strip()

    if stripped.startswith(":"):
        if not is_list:
            problems.append(("错误", "正则前缀 : 只允许用于列表字段"))
        else:
            err = _regex_compile_check(stripped[1:])
            if err:
                problems.append(("警告", err + "（Python 引擎近似）"))
    elif not (lower.startswith("@js:") or lower.startswith("<js>") or "@js:" in lower):
        parts = masked.split("##")
        bal = _balanced(parts[0])
        if bal:
            problems.append(("错误", bal))
        if len(parts) > 1:
            if len(parts) > 4:
                problems.append(("警告", f"## 分 {len(parts)} 段，客户端只取前四段（第 4 段起表示只替换首个匹配）"))
            err = _regex_compile_check(parts[1])
            if err:
                problems.append(("警告", err + "（Python 引擎近似）"))

    for prefix in ("@CSS:", "@XPath:", "@Json:", "@js:"):
        if lower.startswith(prefix) and not stripped[len(prefix):].strip():
            problems.append(("错误", f"{prefix} 后内容为空"))

    if "<js>" in value.lower() and "</js>" not in value.lower():
        problems.append(("错误", "<js> 未闭合"))
    if stripped.startswith("$.") and len(stripped) < 3:
        problems.append(("错误", "$. 后缺少路径"))
    return problems


def lenient_json_load(text: str) -> Any:
    out: list[str] = []
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                nxt = text[i + 1] if i + 1 < len(text) else ""
                if quote == "'" and nxt in ("'", '"'):
                    out.append("\\" + nxt)
                else:
                    out.append(ch + nxt)
                i += 2
                continue
            if ch == quote:
                out.append('"')
                quote = ""
            elif quote == "'" and ch == '"':
                out.append('\\"')
            else:
                out.append(ch)
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            out.append('"')
        else:
            out.append(ch)
        i += 1
    repaired = "".join(out)
    repaired = re.sub(r'(?<=[{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:',
                      lambda m: '"' + m.group(1) + '":', repaired)
    repaired = re.sub(r",\s*([\]}])", r"\1", repaired)
    return json.loads(repaired)


def host_last2(host: str) -> str:
    parts = [p for p in host.lower().split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def split_groups(value: str, seps: list[str]) -> list[str]:
    parts = [value]
    for sep in seps:
        parts = [piece for part in parts for piece in part.split(sep)]
    return [p.strip() for p in parts if p.strip()]


def _host_of(url: Any) -> str:
    if not isinstance(url, str) or "://" not in url:
        return ""
    return url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].lower()


class ReadingAdapter:
    name = "阅读"
    tool_name = "源检测·阅读"
    suite = "阅读P0"
    baseline = "hectorqin/legado@da17bb2"
    implemented = True

    def __init__(self, rules: dict, domain: str = ""):
        self.cfg = rules
        self.limits = rules["limits"]
        self.name_re = re.compile(rules["nameRegex"])
        self.url_re = re.compile(rules["urlRegex"])
        self.comment_re = re.compile(rules["commentRegex"])
        self.cred_re = re.compile(rules["credentialRegex"], re.I)
        self.adult_group_re = re.compile(rules["adultGroupRegex"], re.I)
        self.adult_kw_re = re.compile(rules["adultKeywordRegex"], re.I)
        self.adult_domains = self._load_18plus(rules.get("plus18ListPath", ""))
        self.adult_domains |= {d.lower() for d in rules.get("adultDomainSupplement", [])}
        self.domain = domain or rules.get("域", {}).get("默认", "公开")
        self.adult_mode = rules.get("域", {}).get("取值", {}).get(self.domain, "阻断")

    # ---------- 基础 ----------
    @staticmethod
    def _load_18plus(path: str) -> set[str]:
        domains: set[str] = set()
        if not path or not os.path.isfile(path):
            return domains
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    decoded = base64.b64decode(line).decode("utf-8", "ignore").strip().lower()
                except Exception:
                    continue
                if decoded:
                    domains.add(decoded)
                    domains.add(host_last2(decoded))
        return domains

    def _adult(self, r: EntryResult, message: str, path: str = "") -> None:
        r.tag("成人域")
        if self.adult_mode == "打标":
            r.add("T-09", "警告", "成人域标记：" + message + "（私有域：仅打标，不阻断）", path)
        else:
            r.add("T-09", "错误", message + "（公开域：不通过）", path)

    def coverage(self) -> list[tuple[str, str, str]]:
        return [
            ("T-01", "JSON 可解析、顶层数组、无 BOM、无重复键（RBS-PRC-028）", "自动"),
            ("T-02", "29 个顶层键齐全、无禁用键、无未知键（RBS-PRC-029、RBS-STR-001/RBS-STR-006/RBS-STR-007）", "自动"),
            ("T-03", "bookSourceUrl 形态合规且全批唯一（RBS-PRC-030）", "自动"),
            ("T-04", "bookSourceName 命名合规、同组唯一（跨组同名需备注区别）（RBS-PRC-031、RBS-CLS-035）", "自动"),
            ("T-05", "bookSourceGroup 在白名单、单一归属（RBS-PRC-032、RBS-CLS-002/RBS-CLS-003/RBS-CLS-004）", "自动"),
            ("T-06", "bookSourceType 合法且与分组类型一致（RBS-PRC-033、RBS-CLS-005）", "自动"),
            ("T-07", "搜索/发现入口与必要子字段齐全（RBS-PRC-034、RBS-STR-003/RBS-STR-016）", "自动"),
            ("T-08", "目录/正文/下载规则必需子字段齐全（RBS-PRC-035、RBS-STR-005/RBS-STR-018/RBS-STR-019）", "自动"),
            ("T-09", "成人内容五层静态判定；公开域阻断、私有域只打标「成人域」", "自动+名单"),
            ("T-10", "无 searchKey/searchPage 等禁用变量（RBS-PRC-037、RBS-STR-027）", "自动"),
            ("T-11", "规则中无写死字面量凭证/手机号（RBS-PRC-038、RBS-STR-025）", "自动"),
            ("T-12", "bookSourceComment 来源登记四段完整（RBS-PRC-044）", "自动"),
            ("T-13", "规则表达式结构可解析（RBS-PRC-037 表达式部分）", "自动"),
            ("T-14", "字段类型严格（RBS-PRC-033、RBS-STR-008/RBS-STR-009/RBS-STR-029）", "自动"),
            ("T-15", "exploreUrl 三形态与分类命名合规（RBS-PRC-043、RBS-CLS-007/RBS-CLS-008/RBS-CLS-009）", "自动"),
            ("T-16", "customOrder 批内不重复（RBS-NAM-018）", "自动"),
            ("T-17", "单条体积与 jsLib 体积未超限（RBS-STR-028）", "自动"),
            ("T-18", "清单字段与 baseline/sha256 一致（RBS-PRC-039，需 --清单）", "自动"),
        ]

    def validate(self, files: list[str]) -> tuple[list[EntryResult], list[dict]]:
        loaded: list[LoadedJSON] = []
        global_errors: list[dict] = []
        for path in files:
            try:
                loaded.append(load_json_strict(path))
            except Exception as e:
                global_errors.append({"文件": path, "说明": f"JSON 解析失败：{e}"})
        results, more = self.validate_loaded(loaded)
        return results, global_errors + more

    def validate_loaded(self, loaded: list[LoadedJSON]) -> tuple[list[EntryResult], list[dict]]:
        results: list[EntryResult] = []
        global_errors: list[dict] = []
        seen_urls: dict[str, list[EntryResult]] = {}
        seen_names: dict[str, list[EntryResult]] = {}
        names_by_plain: dict[str, list[tuple[str, EntryResult]]] = {}
        seen_orders: dict[int, list[EntryResult]] = {}

        for lj in loaded:
            path, data = lj.path, lj.data
            if lj.has_bom:
                global_errors.append({"文件": path, "说明": "文件带 UTF-8 BOM，不符合 RBS-PRC-028"})
            if lj.duplicate_keys:
                keys = "、".join(sorted(set(lj.duplicate_keys)))
                global_errors.append({"文件": path, "说明": f"JSON 存在重复键：{keys}"})
            if not isinstance(data, list):
                global_errors.append({"文件": path, "说明": "顶层不是 JSON 数组，不符合 RBS-NAM-003"})
                continue

            for idx, src in enumerate(data, start=1):
                r = self._analyze(path, idx, src)
                results.append(r)
                if isinstance(src, dict):
                    url = src.get("bookSourceUrl")
                    name = src.get("bookSourceName")
                    grp = src.get("bookSourceGroup")
                    if isinstance(url, str) and url:
                        seen_urls.setdefault(url, []).append(r)
                    if isinstance(name, str) and name:
                        grp_key = grp if isinstance(grp, str) else ""
                        key = "%s\t%s" % (grp_key, name)
                        seen_names.setdefault(key, []).append(r)
                        names_by_plain.setdefault(name, []).append((grp_key, r))
                    order = src.get("customOrder")
                    if isinstance(order, int) and not isinstance(order, bool):
                        seen_orders.setdefault(order, []).append(r)

        for url, group in seen_urls.items():
            if len(group) > 1:
                for r in group:
                    r.add("T-03", "错误", f"bookSourceUrl 在批内重复 {len(group)} 次：{url}")
        for key, group in seen_names.items():
            if len(group) > 1:
                grp, name = key.split("\t", 1)
                for r in group:
                    r.add("T-04", "错误",
                          f"同组（{grp}）内 bookSourceName 重复 {len(group)} 次：{name}；"
                          f"第 2 条起应加「·备」，或同一后端重复应合并")
        for name, items in names_by_plain.items():
            grps = {g for g, _ in items}
            if len(grps) > 1:
                for _, r in items:
                    r.add("T-04", "警告",
                          f"跨组同名：{name} 出现在 {len(grps)} 个分组，需在 bookSourceComment 写清区别")
        for order, group in seen_orders.items():
            if len(group) > 1:
                for r in group:
                    r.add("T-16", "警告", f"customOrder={order} 在批内重复 {len(group)} 次")
        return results, global_errors

    # ---------- 单条 ----------
    def _analyze(self, path: str, idx: int, src: Any) -> EntryResult:
        if not isinstance(src, dict):
            r = EntryResult(path, idx, f"(第{idx}项非对象)", "", None, self.domain)
            r.add("T-01", "错误", "条目不是 JSON 对象")
            return r

        name = src.get("bookSourceName")
        url = src.get("bookSourceUrl")
        r = EntryResult(path, idx,
                        name if isinstance(name, str) else "",
                        url if isinstance(url, str) else "",
                        src.get("bookSourceType"), self.domain)

        self._check_keys(r, src)
        self._check_types(r, src)
        self._check_url(r, src)
        self._check_name(r, src)
        self._check_group(r, src)
        self._check_entries(r, src)
        self._check_explore(r, src)
        self._check_required_rules(r, src)
        self._check_rule_syntax_all(r, src)
        self._check_forbidden(r, src)
        self._check_adult(r, src)
        self._check_comment(r, src)
        self._check_limits(r, src)
        r.checks_run = len(self.coverage())
        return r

    def _check_keys(self, r: EntryResult, src: dict) -> None:
        required = set(self.cfg["requiredTopKeys"])
        keys = set(src.keys())
        missing = sorted(required - keys)
        if missing:
            r.add("T-02", "错误", "缺少顶层键：" + "、".join(missing))
        extra = sorted(keys - required - set(self.cfg["forbiddenTopKeys"]))
        if extra:
            r.add("T-02", "错误", "存在规范清单外的顶层键：" + "、".join(extra))
        for key in self.cfg["forbiddenTopKeys"]:
            if key in src:
                r.add("T-02", "错误", f"禁用字段 {key}（本基线不持久化或不存在）")

    def _check_types(self, r: EntryResult, src: dict) -> None:
        for key in ("bookSourceUrl", "bookSourceName", "bookSourceGroup", "bookUrlPattern",
                    "jsLib", "header", "concurrentRate", "bookSourceComment", "variableComment",
                    "exploreUrl", "exploreScreen", "searchUrl"):
            if key in src and src[key] is not None and not isinstance(src[key], str):
                r.add("T-14", "错误", f"{key} 应为字符串，实际 {type(src[key]).__name__}")
        for key in ("enabled", "enabledExplore", "enabledCookieJar"):
            if key in src and not isinstance(src[key], bool):
                r.add("T-14", "错误", f"{key} 应为布尔值，实际 {type(src[key]).__name__}")
        for key in ("bookSourceType", "customOrder", "respondTime", "weight"):
            if key in src and isinstance(src[key], bool):
                r.add("T-14", "错误", f"{key} 应为整数，实际布尔值")
            elif key in src and not isinstance(src[key], int):
                r.add("T-14", "错误", f"{key} 应为整数，实际 {type(src[key]).__name__}")
        if "lastUpdateTime" in src and not isinstance(src["lastUpdateTime"], int):
            r.add("T-14", "错误", "lastUpdateTime 应为毫秒整数")
        for key in ("ruleExplore", "ruleSearch", "ruleBookInfo", "ruleToc", "ruleContent"):
            if key in src and not isinstance(src[key], dict):
                r.add("T-14", "错误", f"{key} 应为对象，实际 {type(src[key]).__name__}")
        info = src.get("ruleBookInfo")
        if isinstance(info, dict) and "canReName" in info and not isinstance(info["canReName"], str):
            r.add("T-14", "错误", "ruleBookInfo.canReName 应为字符串（非空即启用，禁止写布尔）")

        t = src.get("bookSourceType")
        if isinstance(t, int) and not isinstance(t, bool) and t not in (0, 1, 2, 3):
            r.add("T-06", "错误", f"bookSourceType 只允许 0/1/2/3，实际 {t}")

    def _check_url(self, r: EntryResult, src: dict) -> None:
        url = src.get("bookSourceUrl")
        if not isinstance(url, str) or not url:
            r.add("T-03", "错误", "bookSourceUrl 为空")
            return
        if not self.url_re.fullmatch(url):
            r.add("T-03", "错误", f"bookSourceUrl 不符合 ^https?://[a-z0-9.-]+$：{url}")
        lower = url.lower()
        if not lower.startswith(("http://", "https://")):
            r.add("T-03", "错误", "bookSourceUrl 必须是 http/https 绝对地址")
        host = lower.split("://", 1)[1] if "://" in lower else ""
        host = host.split("/", 1)[0].split(":", 1)[0]
        if not host:
            r.add("T-03", "错误", "bookSourceUrl 缺少 host")
            return
        if host_last2(host) in self.adult_domains or host in self.adult_domains:
            self._adult(r, f"命中内置 18+ 域名名单：{host}", "bookSourceUrl")

    def _check_name(self, r: EntryResult, src: dict) -> None:
        name = src.get("bookSourceName")
        if not isinstance(name, str) or not name:
            r.add("T-04", "错误", "bookSourceName 为空")
            return
        if not self.name_re.fullmatch(name):
            r.add("T-04", "错误", f"bookSourceName 不符合命名正则（2–24 字、限中文/字母/数字/·-（））：{name}")
        lmin, lmax = self.limits["nameMin"], self.limits["nameMax"]
        if not (lmin <= len(name) <= lmax):
            r.add("T-04", "错误", f"bookSourceName 长度 {len(name)} 不在 {lmin}–{lmax}")
        if self.adult_kw_re.search(name):
            self._adult(r, f"书源名命中成人关键词：{name}", "bookSourceName")

    def _check_group(self, r: EntryResult, src: dict) -> None:
        group = src.get("bookSourceGroup")
        if not isinstance(group, str) or not group.strip():
            r.add("T-05", "错误", "bookSourceGroup 为空（必须指定分组）")
            return
        groups = split_groups(group, self.cfg["groupSeparators"])
        bad_seps = [s for s in self.cfg.get("forbiddenGroupSeparators", []) if s in group]
        if bad_seps:
            r.add("T-05", "错误", "分组只允许半角逗号分隔，出现：" + "、".join(bad_seps))
        if not groups:
            r.add("T-05", "错误", "bookSourceGroup 拆分后为空")
        if len(groups) > self.limits["maxGroups"]:
            r.add("T-05", "错误", f"分组数 {len(groups)} 超过上限 {self.limits['maxGroups']}")
        unknown = [g for g in groups if g not in self.cfg["allowedGroups"]]
        if unknown:
            r.add("T-05", "错误", "分组不在白名单：" + "、".join(unknown))
        if self.adult_group_re.search(group):
            self._adult(r, f"分组命中成人关键词：{group}", "bookSourceGroup")

        t = src.get("bookSourceType")
        for g in groups:
            rule = self.cfg["typeGroupRules"].get(g)
            if rule is not None and isinstance(t, int) and t != rule:
                r.add("T-06", "错误", f"分组 {g} 要求 bookSourceType={rule}，实际 {t}")

    def _check_entries(self, r: EntryResult, src: dict) -> None:
        search_url = src.get("searchUrl")
        search_rule = src.get("ruleSearch")
        explore_url = src.get("exploreUrl")
        has_search = bool(search_url) or bool(search_rule)
        has_explore = bool(explore_url)
        if not has_search and not has_explore:
            r.add("T-07", "错误", "既无 searchUrl/ruleSearch，也无 exploreUrl，书源不可用")
            return

        if search_url:
            if not isinstance(search_url, str):
                r.add("T-07", "错误", "searchUrl 应为字符串")
            else:
                low = search_url.strip().lower()
                url_part = re.split(r",\s*[\{\[]", search_url, maxsplit=1)[0].strip()
                lp = url_part.lower()
                if low.startswith(("@js:", "<js>")) or url_part.startswith("{{"):
                    pass
                elif lp.startswith(("javascript:", "file:", "content:")):
                    r.add("T-07", "错误", f"searchUrl 不允许该协议：{url_part}")
                elif "://" in lp and not lp.startswith(("http://", "https://")):
                    r.add("T-07", "错误", f"searchUrl 只允许 http/https 或相对路径：{url_part}")
                if "{{key}}" not in search_url and "@js:" not in search_url:
                    r.add("T-07", "错误", "searchUrl 缺关键词变量 {{key}}（或 @js:）")
        if search_rule or search_url:
            if not isinstance(search_rule, dict):
                r.add("T-07", "错误", "searchUrl 存在但 ruleSearch 不是对象")
            else:
                self._require_subfields(r, "T-07", search_rule,
                                        self.cfg["requiredSubFields"]["search"], "ruleSearch")
                ck = search_rule.get("checkKeyWord")
                if not ck:
                    r.add("T-07", "警告", "ruleSearch.checkKeyWord 未填写，将退回全局默认“我的”")
                elif isinstance(ck, str) and self.adult_kw_re.search(ck):
                    self._adult(r, f"checkKeyWord 命中成人关键词：{ck}", "ruleSearch.checkKeyWord")

        if has_explore and not isinstance(explore_url, str):
            r.add("T-07", "错误", "exploreUrl 应为字符串")
        if not has_explore and src.get("enabledExplore") is True:
            r.add("T-07", "错误", "enabledExplore=true 但 exploreUrl 为空")
        if has_explore:
            explore_rule = src.get("ruleExplore")
            explore_rule = explore_rule if isinstance(explore_rule, dict) else {}
            search_obj = search_rule if isinstance(search_rule, dict) else {}
            if explore_rule.get("bookList"):
                self._require_subfields(r, "T-07", explore_rule,
                                        self.cfg["requiredSubFields"]["explore"], "ruleExplore")
            elif not search_obj.get("bookList"):
                r.add("T-07", "错误",
                      "发现列表规则缺失：ruleExplore.bookList 与 ruleSearch.bookList 均为空")

    def _check_explore(self, r: EntryResult, src: dict) -> None:
        raw = src.get("exploreUrl")
        if not isinstance(raw, str) or not raw.strip():
            return
        text = raw.strip()
        lower = text.lower()
        if lower.startswith("<js>") or lower.startswith("@js:"):
            r.add("T-15", "警告", "exploreUrl 由 JS 动态生成，静态无法判定分类结构，需运行期复核")
            return
        if text.startswith("[") or text.startswith("{"):
            try:
                kinds = json.loads(text)
            except Exception as strict_err:
                try:
                    kinds = lenient_json_load(text)
                except Exception:
                    r.add("T-15", "错误", f"exploreUrl 无法解析为 JSON：{strict_err}")
                    return
                r.add("T-15", "警告",
                      "exploreUrl 非严格 JSON（单引号/裸键/尾逗号），客户端 Gson 可解析，建议改写为严格 JSON")
            if not isinstance(kinds, list):
                r.add("T-15", "错误", "exploreUrl 解析结果不是数组")
                return
            self._check_explore_array(r, kinds)
            return
        self._check_explore_legacy(r, text)

    def _check_explore_array(self, r: EntryResult, kinds: list) -> None:
        if len(kinds) > self.limits["maxExploreKinds"]:
            r.add("T-15", "错误", f"发现分类 {len(kinds)} 个，超过上限 {self.limits['maxExploreKinds']}")
        titles: list[str] = []
        usable = 0
        for i, k in enumerate(kinds, start=1):
            if not isinstance(k, dict):
                r.add("T-15", "错误", f"发现分类第 {i} 项不是对象")
                continue
            extra = set(k.keys()) - {"title", "url", "style"}
            if extra:
                r.add("T-15", "错误", f"发现分类第 {i} 项含未知键：" + "、".join(sorted(extra)))
            title = k.get("title")
            if not isinstance(title, str) or not title.strip():
                r.add("T-15", "错误", f"发现分类第 {i} 项 title 为空")
            else:
                titles.append(title)
                self._check_explore_title(r, title, i)
            url = k.get("url")
            if not isinstance(url, str) or not url.strip():
                r.add("T-15", "警告", f"发现分类第 {i} 项 url 为空，点击无响应")
            else:
                usable += 1
        self._check_explore_tail(r, titles, usable)

    def _check_explore_legacy(self, r: EntryResult, text: str) -> None:
        lines = [s for s in re.split(r"(?:&&|\r?\n)+", text) if s.strip()]
        if len(lines) > self.limits["maxExploreKinds"]:
            r.add("T-15", "错误", f"发现分类 {len(lines)} 个，超过上限 {self.limits['maxExploreKinds']}")
        titles: list[str] = []
        usable = 0
        for i, line in enumerate(lines, start=1):
            title, sep, url = line.partition("::")
            title = title.strip()
            url = url.strip() if sep else ""
            if not title:
                r.add("T-15", "错误", f"发现分类第 {i} 项 title 为空")
                continue
            titles.append(title)
            self._check_explore_title(r, title, i)
            if not url:
                r.add("T-15", "警告", f"发现分类「{title}」url 为空，点击无响应")
            else:
                usable += 1
        self._check_explore_tail(r, titles, usable)

    def _check_explore_title(self, r: EntryResult, title: str, i: int) -> None:
        lo, hi = self.limits["exploreTitleMin"], self.limits["exploreTitleMax"]
        if not (lo <= len(title) <= hi):
            r.add("T-15", "错误", f"发现分类 title 长度 {len(title)} 不在 {lo}–{hi}：{title}")
        if self.adult_kw_re.search(title):
            self._adult(r, f"发现分类 title 命中成人关键词：{title}", f"exploreUrl[{i}].title")

    def _check_explore_tail(self, r: EntryResult, titles: list[str], usable: int) -> None:
        if len(titles) != len(set(titles)):
            r.add("T-15", "错误", "发现分类 title 有重复")
        if not titles:
            r.add("T-15", "错误", "exploreUrl 没有可解析的分类")
        elif usable == 0:
            r.add("T-15", "错误", "exploreUrl 没有任何可用分类（url 全空）")

    def _require_subfields(self, r: EntryResult, cid: str, obj: dict, required: list[str], label: str) -> None:
        for key in required:
            value = obj.get(key)
            if value is None or (isinstance(value, str) and not value.strip()) or value == {}:
                r.add(cid, "错误", f"{label}.{key} 为空")

    def _check_required_rules(self, r: EntryResult, src: dict) -> None:
        t = src.get("bookSourceType")
        if t in (0, 1, 2):
            toc = src.get("ruleToc")
            if not isinstance(toc, dict):
                r.add("T-08", "错误", "ruleToc 缺失或不是对象")
            else:
                self._require_subfields(r, "T-08", toc,
                                        self.cfg["requiredSubFields"]["toc"], "ruleToc")
            content = src.get("ruleContent")
            if not isinstance(content, dict):
                r.add("T-08", "错误", "ruleContent 缺失或不是对象")
            else:
                self._require_subfields(r, "T-08", content,
                                        self.cfg["requiredSubFields"]["content"], "ruleContent")
            info = src.get("ruleBookInfo")
            if not isinstance(info, dict) or not info:
                r.add("T-08", "错误", "ruleBookInfo 缺失或为空")
        elif t == 3:
            info = src.get("ruleBookInfo")
            if not isinstance(info, dict):
                r.add("T-08", "错误", "文件源 ruleBookInfo 缺失")
            else:
                self._require_subfields(r, "T-08", info, ["downloadUrls"], "ruleBookInfo")

    def _check_rule_syntax_all(self, r: EntryResult, src: dict) -> None:
        list_fields = {"bookList", "chapterList", "downloadUrls"}
        for obj_key in ("ruleSearch", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent"):
            obj = src.get(obj_key)
            if not isinstance(obj, dict):
                continue
            for field, value in obj.items():
                for level, msg in check_rule_syntax(value, field, field in list_fields):
                    r.add("T-13", level, f"{obj_key}.{field}：{msg}")

    def _check_forbidden(self, r: EntryResult, src: dict) -> None:
        text_parts: list[str] = []
        for key, value in src.items():
            if isinstance(value, str):
                text_parts.append(value)
            elif isinstance(value, dict):
                text_parts.append(json.dumps(value, ensure_ascii=False))
        joined = "\n".join(text_parts)
        for var in self.cfg["forbiddenVars"]:
            if var in joined:
                r.add("T-10", "错误", f"出现 3.x 不支持的变量：{var}")
        m = self.cred_re.search(joined)
        if m:
            r.add("T-11", "错误", f"规则中出现疑似写死凭证/手机号：{m.group(0)[:40]}")

    def _adult_hits(self, src: dict) -> list[str]:
        hits: list[str] = []
        own_host = host_last2(_host_of(src.get("bookSourceUrl")))
        name = src.get("bookSourceName")
        if isinstance(name, str) and self.adult_kw_re.search(name):
            hits.append(f"书源名：{name}")
        group = src.get("bookSourceGroup")
        if isinstance(group, str) and self.adult_group_re.search(group):
            hits.append(f"分组：{group}")
        url_host = _host_of(src.get("bookSourceUrl"))
        if url_host and (host_last2(url_host) in self.adult_domains or url_host in self.adult_domains):
            hits.append(f"域名：{url_host}")
        text_parts: list[str] = []
        for key, value in src.items():
            if isinstance(value, str):
                text_parts.append(value)
            elif isinstance(value, dict):
                text_parts.append(json.dumps(value, ensure_ascii=False))
        for host in re.findall(r"https?://([A-Za-z0-9.-]+)", "\n".join(text_parts)):
            last2 = host_last2(host)
            if last2 == own_host:
                continue
            if last2 in self.adult_domains or host.lower() in self.adult_domains:
                hits.append(f"引用域名：{host}")
        for host in []:
            pass
        return hits

    def _check_adult(self, r: EntryResult, src: dict) -> None:
        own_host = host_last2(_host_of(src.get("bookSourceUrl")))

        text_parts: list[str] = []
        for key, value in src.items():
            if isinstance(value, str):
                text_parts.append(value)
            elif isinstance(value, dict):
                text_parts.append(json.dumps(value, ensure_ascii=False))
        for host in re.findall(r"https?://([A-Za-z0-9.-]+)", "\n".join(text_parts)):
            last2 = host_last2(host)
            if last2 == own_host:
                continue
            if last2 in self.adult_domains or host.lower() in self.adult_domains:
                self._adult(r, f"规则内引用 18+ 名单域名：{host}", "规则内 URL")

    def _check_comment(self, r: EntryResult, src: dict) -> None:
        comment = src.get("bookSourceComment")
        if not isinstance(comment, str) or not comment.strip():
            r.add("T-12", "错误", "bookSourceComment 为空，缺少来源登记")
            return
        if not self.comment_re.search(comment):
            r.add("T-12", "错误", "bookSourceComment 未按“来源；基线；探活；复探”四段登记")

    def _check_limits(self, r: EntryResult, src: dict) -> None:
        size = len(json.dumps(src, ensure_ascii=False).encode("utf-8"))
        if size > self.limits["entryMax"]:
            r.add("T-17", "警告", f"单条体积 {size} 字节，超过 {self.limits['entryMax']}")
        js_lib = src.get("jsLib")
        if isinstance(js_lib, str) and len(js_lib.encode("utf-8")) > self.limits["jsLibMax"]:
            r.add("T-17", "错误", f"jsLib 体积超过 {self.limits['jsLibMax']} 字节")
        weight = src.get("weight")
        if isinstance(weight, int):
            lo, hi = self.limits["weightMin"], self.limits["weightMax"]
            if not (lo <= weight <= hi):
                r.add("T-17", "警告", f"weight={weight} 不在 {lo}..{hi}")
        respond = src.get("respondTime")
        if isinstance(respond, int) and respond < 0:
            r.add("T-14", "警告", "respondTime 为负数")
        last = src.get("lastUpdateTime")
        if isinstance(last, int) and not (10 ** 12 <= last < 10 ** 14):
            r.add("T-14", "警告", f"lastUpdateTime={last} 不像 13 位毫秒时间戳")

    # ---------- 探活 ----------
    def probe(self, loaded: list[LoadedJSON], results: list[EntryResult],
              limit: int = 0) -> list[dict]:
        cfg = self.cfg.get("探活", {})
        if not cfg.get("启用", False):
            return []
        cap = limit or int(cfg.get("采样上限", 20))
        targets: dict[tuple[str, int], dict] = {}
        for lj in loaded:
            if not isinstance(lj.data, list):
                continue
            for idx, src in enumerate(lj.data, start=1):
                if isinstance(src, dict):
                    targets[(lj.path, idx)] = src
        done = 0
        for r in results:
            if done >= cap:
                break
            src = targets.get((r.file, r.index))
            if not src:
                continue
            built, reason = self._search_request(src, cfg)
            if not built:
                r.probe = ProbeResult("跳过", "C", 0, reason)
                done += 1
                continue
            url, method, headers, body = built
            res = probe_api.request_with_retry(
                url, method=method, headers=headers, body=body,
                timeout=float(cfg.get("总超时秒", 60)),
                retries=int(cfg.get("重试", 1)),
                interval=float(cfg.get("重试间隔秒", 1)))
            if res["status"] == 200 and res["bytes"] >= int(cfg.get("最小响应字节", 200)):
                r.probe = ProbeResult(
                    "通过", "C", res["elapsed_ms"],
                    f"搜索段网络可达（{res['bytes']} 字节，{res['elapsed_ms']}ms）；"
                    f"详情/目录/正文未执行规则解析，按待复核记 C",
                    [{"名称": "搜索", "URL": url, "状态码": 200, "耗时毫秒": res["elapsed_ms"],
                      "结论": "通过", "说明": ""}])
            elif res["status"] == 200:
                r.probe = ProbeResult(
                    "跳过", "C", res["elapsed_ms"],
                    f"搜索段 HTTP 200 但响应仅 {res['bytes']} 字节，无法确认有效，记 C",
                    [{"名称": "搜索", "URL": url, "状态码": 200, "耗时毫秒": res["elapsed_ms"],
                      "结论": "跳过", "说明": "响应过短"}])
            else:
                r.probe = ProbeResult(
                    "失败", "D", res["elapsed_ms"],
                    f"搜索段失败：{res['error'] or ('HTTP-' + str(res['status']))}",
                    [{"名称": "搜索", "URL": url, "状态码": res["status"],
                      "耗时毫秒": res["elapsed_ms"], "结论": "失败",
                      "说明": res["error"]}])
            done += 1
        return []

    def _search_request(self, src: dict, cfg: dict) -> tuple[Any, str]:
        raw = src.get("searchUrl")
        if not isinstance(raw, str) or not raw.strip():
            return None, "无 searchUrl，仅发现源，未探活"
        text = raw.strip()
        lower = text.lower()
        if lower.startswith(("@js:", "<js>")) or text.startswith("{{"):
            return None, "searchUrl 为 JS/变量驱动，静态无法构造"
        option: dict = {}
        cut = text.rfind(",{")
        if cut >= 0:
            try:
                option = json.loads(text[cut + 1:])
                text = text[:cut]
            except Exception:
                option = {}
        if "<js>" in text.lower() or "@js:" in text.lower():
            return None, "searchUrl 含内联 JS，静态无法构造"
        keyword = str(cfg.get("关键词", "我的"))
        text = text.replace("{{key}}", urllib.parse.quote(keyword))
        text = text.replace("{{page}}", "1")
        text = re.sub(r"<([^<>]+)>", lambda m: m.group(1).split(",")[0], text)
        if "{{" in text:
            return None, "searchUrl 含未知变量，静态无法构造"
        base = src.get("bookSourceUrl")
        if not isinstance(base, str) or not base:
            return None, "bookSourceUrl 为空，无法绝对化搜索地址"
        if text.startswith("//"):
            scheme = base.split(":", 1)[0]
            url = f"{scheme}:{text}"
        elif text.lower().startswith(("http://", "https://")):
            url = text
        else:
            url = urllib.parse.urljoin(base.rstrip("/") + "/", text.lstrip("/"))
        method = str(option.get("method", "GET")).upper()
        headers = option.get("headers") if isinstance(option.get("headers"), dict) else None
        body = option.get("body")
        if body is None:
            body_bytes = None
        elif isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        return (url, method, headers, body_bytes), ""

    # ---------- 修复 / 补充 ----------
    def build_plan(self, loaded: list[LoadedJSON], do_repair: bool = True,
                   do_supplement: bool = True) -> RepairPlan:
        plan = RepairPlan()
        data_by_file: dict[str, Any] = {}
        for lj in loaded:
            data_by_file[lj.path] = copy.deepcopy(lj.data)
        plan.original = {lj.path: copy.deepcopy(lj.data) for lj in loaded}
        plan.data = data_by_file

        fix_cfg = self.cfg.get("修复", {})
        sup_cfg = self.cfg.get("补充", {})
        fixes = set(fix_cfg.get("启用动作", [])) if do_repair else set()
        sups = set(sup_cfg.get("启用动作", [])) if do_supplement else set()

        for lj in loaded:
            data = data_by_file[lj.path]
            if not isinstance(data, list):
                continue
            orders: list[int] = []
            for src in data:
                if isinstance(src, dict):
                    order = src.get("customOrder")
                    if isinstance(order, int) and not isinstance(order, bool):
                        orders.append(order)
            duplicate_order = len(orders) != len(set(orders))

            for idx, src in enumerate(data, start=1):
                if not isinstance(src, dict):
                    continue
                name = src.get("bookSourceName") if isinstance(src.get("bookSourceName"), str) else ""
                if "F-01" in fixes:
                    self._repair_defaults(plan, lj.path, idx, name, src, fix_cfg)
                if "F-08" in fixes:
                    self._repair_forbidden_keys(plan, lj.path, idx, name, src)
                if "F-02" in fixes:
                    self._repair_group(plan, lj.path, idx, name, src, fix_cfg)
                if "F-03" in fixes:
                    self._repair_name(plan, lj.path, idx, name, src)
                if "F-04" in fixes:
                    self._repair_url(plan, lj.path, idx, name, src)
                if "F-06" in fixes:
                    self._repair_hash_segments(plan, lj.path, idx, name, src)
                if "F-07" in fixes:
                    self._repair_can_rename(plan, lj.path, idx, name, src, fix_cfg)
                if "S-03" in sups:
                    self._supplement_group(plan, lj.path, idx, name, src, sup_cfg)
                if "S-01" in sups:
                    self._supplement_keyword(plan, lj.path, idx, name, src, sup_cfg)
                if "S-02" in sups:
                    self._supplement_comment(plan, lj.path, idx, name, src, sup_cfg)

                hits = self._adult_hits(src)
                if hits and self.adult_mode == "阻断":
                    plan.unhandle(lj.path, idx, name, "成人内容命中公开域：" + "、".join(hits),
                                  "内容判断类，工具不自动删除或改分组",
                                  "移入私有域（--域 私有）或私有书源包，公开包不收录")

            if "F-05" in fixes and duplicate_order:
                for idx, src in enumerate(data, start=1):
                    if not isinstance(src, dict):
                        continue
                    name = src.get("bookSourceName") if isinstance(src.get("bookSourceName"), str) else ""
                    self._repair_order(plan, lj.path, idx, name, src, idx - 1)

            self._note_duplicates(plan, lj.path, data)
        return plan

    def _repair_defaults(self, plan: RepairPlan, file: str, idx: int, name: str,
                         src: dict, cfg: dict) -> None:
        for key, value in cfg.get("默认字段", {}).items():
            if key not in src:
                src[key] = copy.deepcopy(value)
                plan.add("F-01", "修复", file, idx, name, key, _MISSING, value,
                         "缺少基础字段，按规范默认值补齐（RBS-STR-001/RBS-STR-010）")

    def _repair_group(self, plan: RepairPlan, file: str, idx: int, name: str,
                      src: dict, cfg: dict) -> None:
        raw = src.get("bookSourceGroup")
        if not isinstance(raw, str) or not raw.strip():
            return
        parts = split_groups(raw, cfg.get("分组分隔符", [",", ";", "，", "；"]))
        aliases = cfg.get("分组别名", {})
        mapped = [aliases.get(p, p) for p in parts]
        unresolved: list[str] = []
        for i, p in enumerate(mapped):
            if p in self.cfg["allowedGroups"]:
                continue
            cleaned = re.sub(r"^[^\u4e00-\u9fa5A-Za-z0-9]+", "", p)
            cleaned = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+$", "", cleaned)
            if cleaned in self.cfg["allowedGroups"]:
                mapped[i] = cleaned
            else:
                unresolved.append(p)
        if unresolved:
            plan.unhandle(file, idx, name, "分组不在白名单：" + "、".join(unresolved),
                          "去除装饰符后仍无确定性映射", "人工确认分组或补充白名单")
            return
        if len(mapped) > self.limits["maxGroups"]:
            plan.unhandle(file, idx, name, f"分组数 {len(mapped)} 超过 {self.limits['maxGroups']}",
                          "删减分组属于内容判断", "人工确认保留哪些分组")
            return
        new = ",".join(mapped)
        if new != raw:
            src["bookSourceGroup"] = new
            plan.add("F-02", "修复", file, idx, name, "bookSourceGroup", raw, new,
                     "分组名归一到白名单并用半角逗号分隔（RBS-CLS-002/RBS-CLS-003）")

    def _repair_forbidden_keys(self, plan: RepairPlan, file: str, idx: int,
                               name: str, src: dict) -> None:
        for key in self.cfg.get("forbiddenTopKeys", []):
            if key in src:
                old = src.pop(key)
                plan.add("F-08", "修复", file, idx, name, key, old, _MISSING,
                         "删除本基线不存在且客户端不读取的禁用键（RBS-STR-006/RBS-STR-007）")

    def _repair_name(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        raw = src.get("bookSourceName")
        if not isinstance(raw, str) or not raw.strip():
            return
        new = re.sub(r"[\x00-\x1f\x7f]", "", raw).strip()
        new = re.sub(r"\s{2,}", " ", new)
        if new != raw:
            src["bookSourceName"] = new
            plan.add("F-03", "修复", file, idx, new, "bookSourceName", raw, new,
                     "去除首尾空白/控制字符/连续空格（RBS-NAM-008）")
        if not self.name_re.fullmatch(new) or not (self.limits["nameMin"] <= len(new) <= self.limits["nameMax"]):
            plan.unhandle(file, idx, new or name, f"命名仍不合规：{new}",
                          "改名属于人工判断，工具不做猜测", "按「站点简称-用途」重命名")

    def _repair_url(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        raw = src.get("bookSourceUrl")
        if not isinstance(raw, str) or not raw.strip():
            return
        text = raw.strip()
        m = re.match(r"(?i)(https?://)([^/]+)(/)?$", text)
        if not m:
            return
        scheme, host = m.group(1).lower(), m.group(2).lower()
        new = f"{scheme}{host}"
        if new != raw:
            src["bookSourceUrl"] = new
            plan.add("F-04", "修复", file, idx, name, "bookSourceUrl", raw, new,
                     "去首尾空白/末尾斜杠，host 转小写（RBS-NAM-014/RBS-NAM-015）")

    def _repair_can_rename(self, plan: RepairPlan, file: str, idx: int, name: str,
                           src: dict, cfg: dict) -> None:
        info = src.get("ruleBookInfo")
        if not isinstance(info, dict) or "canReName" not in info:
            return
        raw = info["canReName"]
        if not isinstance(raw, bool):
            return
        new = cfg.get("canReName真值", "1") if raw else cfg.get("canReName假值", "")
        info["canReName"] = new
        plan.add("F-07", "修复", file, idx, name, "ruleBookInfo.canReName", raw, new,
                 "布尔值改为字符串：true→非空(启用)、false→空串(禁用)，保持原语义（RBS-STR-029）")

    def _repair_order(self, plan: RepairPlan, file: str, idx: int, name: str,
                      src: dict, new_order: int) -> None:
        raw = src.get("customOrder")
        if raw is None:
            return
        if raw == new_order:
            return
        src["customOrder"] = new_order
        plan.add("F-05", "修复", file, idx, name, "customOrder", raw, new_order,
                 "包内 customOrder 重复/不连续，按数组顺序重排为 0..n-1（RBS-NAM-018）")

    def _repair_hash_segments(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        for obj_key in ("ruleSearch", "ruleExplore", "ruleBookInfo", "ruleToc", "ruleContent"):
            obj = src.get(obj_key)
            if not isinstance(obj, dict):
                continue
            for field, value in obj.items():
                if not isinstance(value, str) or "##" not in value:
                    continue
                if "{{" in value or "<js>" in value.lower():
                    continue
                parts = value.split("##")
                new = value
                if len(parts) == 2 and parts[1] == "":
                    new = parts[0]
                elif len(parts) > 4:
                    while len(parts) > 4 and parts[-1] == "":
                        parts = parts[:-1]
                    if len(parts) > 4:
                        plan.unhandle(file, idx, name, f"{obj_key}.{field} 的 ## 分 {len(parts)} 段且非空",
                                      "合并/删除段会改变替换语义", "人工确认保留哪几段")
                        continue
                    new = "##".join(parts)
                if new != value:
                    obj[field] = new
                    plan.add("F-06", "修复", file, idx, name, f"{obj_key}.{field}", value, new,
                             "修正 ## 段数：去掉尾部空段/尾部单个 ##（RBS-STR-039）")

    def _supplement_group(self, plan: RepairPlan, file: str, idx: int, name: str,
                          src: dict, cfg: dict) -> None:
        raw = src.get("bookSourceGroup")
        if isinstance(raw, str) and raw.strip():
            return
        t = src.get("bookSourceType")
        default = cfg.get("按类型分组", {}).get(str(t), cfg.get("默认分组", "待校验"))
        src["bookSourceGroup"] = default
        plan.add("S-03", "补充", file, idx, name, "bookSourceGroup", raw if raw is not None else _MISSING,
                 default, f"按 bookSourceType={t} 归入白名单分组 {default}（RBS-CLS-001/RBS-CLS-005）")

    def _supplement_keyword(self, plan: RepairPlan, file: str, idx: int, name: str,
                            src: dict, cfg: dict) -> None:
        rule = src.get("ruleSearch")
        if not isinstance(rule, dict) or rule.get("checkKeyWord"):
            return
        kw_cfg = cfg.get("checkKeyWord", {})
        if not kw_cfg.get("启用", True):
            return
        base = re.split(r"[-·（）()]", name)[0].strip()
        candidate = base
        for word in kw_cfg.get("剔除词", []):
            candidate = candidate.replace(word, "")
        lo = int(kw_cfg.get("长度最小", 2))
        hi = int(kw_cfg.get("长度最大", 6))
        if lo <= len(candidate) <= hi and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9]+", candidate):
            rule["checkKeyWord"] = candidate
            plan.add("S-01", "补充", file, idx, name, "ruleSearch.checkKeyWord", _MISSING,
                     candidate, "由书源名可推断出 2–6 字关键词（RBS-STR-020）")
        else:
            plan.unhandle(file, idx, name, "checkKeyWord 为空且无法从名称推断",
                          "推断结果不满足 2–6 字或含非中文数字字符", "人工填写站点真实存在的书名/作者")

    def _supplement_comment(self, plan: RepairPlan, file: str, idx: int, name: str,
                            src: dict, cfg: dict) -> None:
        raw = src.get("bookSourceComment")
        if isinstance(raw, str) and raw.strip() and self.comment_re.search(raw):
            return
        template = cfg.get("注释模板", "来源：待补；基线：{基线}；探活：C；复探：{日期}")
        header = template.replace("{基线}", self.baseline).replace("{日期}", _today())
        if isinstance(raw, str) and raw.strip():
            new = header + "\n" + raw
            reason = "在原注释前补四段登记头，保留原内容（RBS-CLS-011）"
        else:
            new = header
            reason = "按四段注释模板预填，来源需人工补填（RBS-CLS-011）"
        src["bookSourceComment"] = new
        plan.add("S-02", "补充", file, idx, name, "bookSourceComment",
                 raw if raw is not None else _MISSING, new, reason, need_confirm=True)

    def _note_duplicates(self, plan: RepairPlan, file: str, data: list) -> None:
        urls: dict[str, list[int]] = {}
        names: dict[str, list[int]] = {}
        for idx, src in enumerate(data, start=1):
            if not isinstance(src, dict):
                continue
            u, n = src.get("bookSourceUrl"), src.get("bookSourceName")
            if isinstance(u, str) and u:
                urls.setdefault(u, []).append(idx)
            if isinstance(n, str) and n:
                names.setdefault(n, []).append(idx)
        for u, group in urls.items():
            if len(group) > 1:
                for idx in group:
                    src = data[idx - 1]
                    plan.unhandle(file, idx, src.get("bookSourceName", ""),
                                  f"bookSourceUrl 重复：{u}", "删哪条属于内容判断",
                                  "人工确认保留哪一条并删除其余")
        for n, group in names.items():
            if len(group) > 1:
                for idx in group:
                    src = data[idx - 1]
                    plan.unhandle(file, idx, n, f"bookSourceName 重复：{n}",
                                  "改名属于人工判断", "按「站点简称-用途/主备」区分")

    # ---------- 清单 ----------
    def validate_manifest(self, manifest_path: str, source_file: str) -> list[dict]:
        problems: list[dict] = []
        try:
            manifest = json.load(open(manifest_path, "r", encoding="utf-8-sig"))
        except Exception as e:
            return [{"文件": manifest_path, "说明": f"清单 JSON 解析失败：{e}"}]
        required = ["name", "version", "generatedAt", "entries", "sha256",
                    "baseline", "probeSummary", "excluded", "owner", "changelog"]
        for key in required:
            if key not in manifest:
                problems.append({"文件": manifest_path, "说明": f"清单缺少字段 {key}"})
        if manifest.get("baseline") != self.baseline:
            problems.append({"文件": manifest_path,
                             "说明": f"清单 baseline 应为 {self.baseline}，实际 {manifest.get('baseline')}"})
        actual_entries = None
        if os.path.isfile(source_file):
            try:
                data = json.load(open(source_file, "r", encoding="utf-8-sig"))
                if isinstance(data, list):
                    actual_entries = len(data)
            except Exception:
                pass
        if actual_entries is not None and manifest.get("entries") != actual_entries:
            problems.append({"文件": manifest_path,
                             "说明": f"清单 entries={manifest.get('entries')}，书源实际 {actual_entries} 条"})
        summary = manifest.get("probeSummary")
        if not isinstance(summary, dict):
            problems.append({"文件": manifest_path, "说明": "probeSummary 不是对象"})
        else:
            try:
                total = sum(int(summary.get(k, 0)) for k in ("A", "B", "C", "D"))
                if total != manifest.get("entries"):
                    problems.append({"文件": manifest_path,
                                     "说明": f"probeSummary 四档之和 {total} ≠ entries {manifest.get('entries')}"})
            except (TypeError, ValueError):
                problems.append({"文件": manifest_path, "说明": "probeSummary 含非整数值"})
        if not isinstance(manifest.get("excluded"), int) or isinstance(manifest.get("excluded"), bool):
            problems.append({"文件": manifest_path, "说明": "excluded 应为整数"})
        if os.path.isfile(source_file) and manifest.get("sha256"):
            import hashlib
            actual = hashlib.sha256(open(source_file, "rb").read()).hexdigest().upper()
            if actual != str(manifest["sha256"]).upper():
                problems.append({"文件": manifest_path, "说明": f"sha256 不匹配：清单 {manifest['sha256']}，实际 {actual}"})
        return problems


def _today() -> str:
    from core import date_text
    return date_text()


def load_rules(path: str) -> dict:
    return json.load(open(path, "r", encoding="utf-8-sig"))
