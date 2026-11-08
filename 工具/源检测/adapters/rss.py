"""阅读（Legado 3.x）订阅源 / rssSource 适配器。

与书源适配器并列、字段集合互不复用：
- 书源：adapters/reading.py + rules/阅读.json（bookSource，29 个顶层键）；
- 订阅源：本文件 + rules/阅读-订阅源.json（rssSource，字段表见规则文件，逐条标注基线行号）。

判定依据全部来自本地基线 hectorqin/legado@da17bb2：
- 实体字段与默认值：RssSource.kt:15-95
- 导入唯一硬校验（sourceUrl 非空）：ImportRssSourceViewModel.kt:131/141/171-173
- 列表规则为空走默认 XML 解析：RssParserByRule.kt:39-42、RssParserDefault.kt:36-113
- 标题为空丢弃条目、链接回落源地址：RssParserByRule.kt:125-129
- 分类地址拆分与回退：RssSourceExtensions.kt:17-56、RssViewModel.kt:48-74
- singleUrl 直接打开首条分类：RssFragment.kt:181-196
- articleStyle 越界走默认样式：RssArticlesFragment.kt:51-55
- 请求头 JSON 与登录 UI 解析：BaseSource.kt:67-133
"""

from __future__ import annotations

import copy
import json
import os
import re
import urllib.parse
from typing import Any

import probe as probe_api
from adapters.reading import (ReadingAdapter, check_rule_syntax, host_last2,
                              lenient_json_load, split_groups, _host_of)
from core import EntryResult, LoadedJSON, ProbeResult, date_text, load_json_strict
from repair import RepairPlan, _MISSING


class RssAdapter:
    name = "阅读-订阅源"
    tool_name = "源检测·阅读订阅源"
    suite = "阅读订阅源P0"
    baseline = "hectorqin/legado@da17bb2"
    module = "rssSource"
    implemented = True
    record_app = "阅读"          # 记录仍落 记录/<日期>/阅读/，与书源同目录
    report_prefix = "订阅源"      # 报告文件名加前缀，避免与书源报告混淆

    def __init__(self, rules: dict, domain: str = ""):
        self.cfg = rules
        self.limits = rules["limits"]
        self.fields = {row["字段"]: row for row in rules["字段表"]}
        self.allowed = set(self.fields)
        self.required = set(rules["requiredTopKeys"])
        self.name_re = re.compile(rules["nameRegex"])
        self.url_re = re.compile(rules["urlRegex"])
        self.cred_re = re.compile(rules["credentialRegex"], re.I)
        self.adult_group_re = re.compile(rules["adultGroupRegex"], re.I)
        self.adult_kw_re = re.compile(rules["adultKeywordRegex"], re.I)
        self.comment_re = re.compile(
            "来源[:：][^；]+；基线[:：][^；]+；探活[:：][ABCD][^；]*；复探[:：]\\d{4}-\\d{2}-\\d{2}")
        self.adult_domains = ReadingAdapter._load_18plus(rules.get("plus18ListPath", ""))
        self.adult_domains |= {d.lower() for d in rules.get("adultDomainSupplement", [])}
        self.domain = domain or rules.get("域", {}).get("默认", "公开")
        self.adult_mode = rules.get("域", {}).get("取值", {}).get(self.domain, "阻断")

    # ---------- 基础 ----------
    def _adult(self, r: EntryResult, message: str, path: str = "") -> None:
        r.tag("成人域")
        if self.adult_mode == "打标":
            r.add("T-09", "警告", "成人域标记：" + message + "（私有域：仅打标，不阻断）", path)
        else:
            r.add("T-09", "错误", message + "（公开域：不通过）", path)

    def coverage(self) -> list[tuple[str, str, str]]:
        return [
            ("T-01", "JSON 可解析、顶层数组、无 BOM、无重复键", "自动"),
            ("T-02", "字段集合：sourceUrl/sourceName 必填、未知键、实体字段类型", "自动"),
            ("T-03", "sourceUrl 形态合规且批内唯一（主键约束）", "自动"),
            ("T-04", "sourceName 非空、无控制字符、同组重名为 0（跨组同名需备注区别）", "自动"),
            ("T-05", "sourceGroup 拆分、分组数、白名单与空组名", "自动"),
            ("T-06", "articleStyle 0–2、customOrder、lastUpdateTime、concurrentRate", "自动"),
            ("T-07", "sortUrl 行语法（名称::链接）、JS 形态、singleUrl 组合", "自动"),
            ("T-08", "规则完整性：列表/标题/链接/翻页依赖", "自动"),
            ("T-09", "成人内容五层静态判定；公开域阻断、私有域只打标「成人域」", "自动+名单"),
            ("T-10", "规则表达式结构可解析（8 个规则字段 + sortUrl）", "自动"),
            ("T-11", "无写死字面量凭证/手机号", "自动"),
            ("T-12", "header/loginUi/jsLib 的 JSON 可解析", "自动"),
            ("T-13", "单条体积、jsLib 体积、内联 JS 长度", "自动"),
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
            if lj.has_bom:
                global_errors.append({"文件": lj.path, "说明": "文件带 UTF-8 BOM，不符合 T-01"})
            if lj.duplicate_keys:
                keys = "、".join(sorted(set(lj.duplicate_keys)))
                global_errors.append({"文件": lj.path, "说明": f"JSON 存在重复键：{keys}"})
            if not isinstance(lj.data, list):
                global_errors.append({"文件": lj.path,
                                      "说明": "顶层不是 JSON 数组，订阅源应为 rssSource 数组"})
                continue

            for idx, src in enumerate(lj.data, start=1):
                r = self._analyze(lj.path, idx, src)
                results.append(r)
                if isinstance(src, dict):
                    url = src.get("sourceUrl")
                    name = src.get("sourceName")
                    if isinstance(url, str) and url.strip():
                        seen_urls.setdefault(url.strip(), []).append(r)
                    if isinstance(name, str) and name.strip():
                        grp = src.get("sourceGroup")
                        grp_key = grp.strip() if isinstance(grp, str) else ""
                        key = "%s\t%s" % (grp_key, name.strip())
                        seen_names.setdefault(key, []).append(r)
                        names_by_plain.setdefault(name.strip(), []).append((grp_key, r))
                    order = src.get("customOrder")
                    if isinstance(order, int) and not isinstance(order, bool):
                        seen_orders.setdefault(order, []).append(r)

        for url, group in seen_urls.items():
            if len(group) > 1:
                for r in group:
                    r.add("T-03", "错误", f"sourceUrl 在批内重复 {len(group)} 次（主键冲突）：{url}")
        for key, group in seen_names.items():
            if len(group) > 1:
                grp, name = key.split("\t", 1)
                for r in group:
                    r.add("T-04", "错误",
                          f"同组（{grp}）内 sourceName 重复 {len(group)} 次：{name}；"
                          f"第 2 条起应加「·备」，或同一后端重复应合并")
        for name, items in names_by_plain.items():
            grps = {g for g, _ in items}
            if len(grps) > 1:
                for _, r in items:
                    r.add("T-04", "警告",
                          f"跨组同名：{name} 出现在 {len(grps)} 个分组，需在 sourceComment 写清区别")
        for order, group in seen_orders.items():
            if len(group) > 1:
                for r in group:
                    r.add("T-06", "警告", f"customOrder={order} 在批内重复 {len(group)} 次")
        return results, global_errors

    # ---------- 单条 ----------
    def _analyze(self, path: str, idx: int, src: Any) -> EntryResult:
        if not isinstance(src, dict):
            r = EntryResult(path, idx, f"(第{idx}项非对象)", "", None, self.domain)
            r.add("T-01", "错误", "条目不是 JSON 对象")
            return r
        name = src.get("sourceName")
        url = src.get("sourceUrl")
        r = EntryResult(path, idx,
                        name.strip() if isinstance(name, str) else "",
                        url.strip() if isinstance(url, str) else "",
                        self.module, self.domain)
        self._check_keys(r, src)
        self._check_url(r, src)
        self._check_name(r, src)
        self._check_group(r, src)
        self._check_numbers(r, src)
        self._check_sort_url(r, src)
        self._check_rules(r, src)
        self._check_rule_syntax(r, src)
        self._check_json_fields(r, src)
        self._check_credentials(r, src)
        self._check_sizes(r, src)
        self._check_adult(r, src)
        r.checks_run = len(self.coverage())
        return r

    def _check_keys(self, r: EntryResult, src: dict) -> None:
        missing = sorted(self.required - set(src.keys()))
        if missing:
            r.add("T-02", "错误", "缺少必填字段：" + "、".join(missing))
        extra = sorted(set(src.keys()) - self.allowed)
        if extra:
            r.add("T-02", "错误", "存在实体未定义字段（GSON 导入时会被丢弃）：" + "、".join(extra))
        for key in self.fields:
            if key not in src:
                continue
            value = src[key]
            if value is None:
                if key in self.required:
                    r.add("T-02", "错误", f"{key} 为 null（必填）")
                continue
            if key in self.cfg["stringFields"] and not isinstance(value, str):
                r.add("T-02", "错误", f"{key} 应为字符串，实际 {type(value).__name__}")
            elif key in self.cfg["boolFields"] and not isinstance(value, bool):
                r.add("T-02", "错误", f"{key} 应为布尔值，实际 {type(value).__name__}")
            elif key in self.cfg["intFields"]:
                if isinstance(value, bool) or not isinstance(value, int):
                    r.add("T-02", "错误", f"{key} 应为整数，实际 {type(value).__name__}")
        if isinstance(src.get("sourceUrl"), str) and src["sourceUrl"] != src["sourceUrl"].strip():
            r.add("T-02", "警告", "sourceUrl 首尾有空白字符")
        if isinstance(src.get("sourceName"), str) and src["sourceName"] != src["sourceName"].strip():
            r.add("T-04", "警告", "sourceName 首尾有空白字符")

    def _check_url(self, r: EntryResult, src: dict) -> None:
        url = src.get("sourceUrl")
        if not isinstance(url, str) or not url.strip():
            r.add("T-03", "错误", "sourceUrl 为空（导入即报「不是订阅源」，ImportRssSourceViewModel.kt:131-133）")
            return
        text = url.strip()
        low = text.lower()
        if low.startswith(("@js:", "<js>")):
            if low.startswith("<js>") and not low.rstrip().endswith("</js>"):
                r.add("T-03", "错误", "sourceUrl 的 <js> 未闭合（AnalyzeUrl.kt:153-176）")
            if len(text) > self.limits["inlineJsMax"]:
                r.add("T-13", "警告",
                      f"sourceUrl 内联 JS {len(text)} 字符，超过 {self.limits['inlineJsMax']}")
            return
        base, option = self._split_url_option(text)
        if option:
            self._check_url_option(r, option, "sourceUrl")
        url = base
        if "://" not in url:
            r.add("T-03", "错误", f"sourceUrl 不是绝对地址：{url}")
            return
        scheme = url.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            r.add("T-03", "错误", f"sourceUrl 只允许 http/https，实际 {scheme}")
        if not self.url_re.fullmatch(url):
            r.add("T-03", "错误", f"sourceUrl 不符合 ^https?://host[:port][/path]：{url}")
        host = _host_of(url)
        if host and (host_last2(host) in self.adult_domains or host in self.adult_domains):
            self._adult(r, f"命中内置 18+ 域名名单：{host}", "sourceUrl")

    @staticmethod
    def _split_url_option(text: str) -> tuple[str, str]:
        """按 AnalyzeUrl.paramPattern（\\s*,\\s*(?=\\{)）拆出链接后置 JSON 选项。

        依据 AnalyzeUrl.kt:669 与 :213-254：URL 可带 `,{...}` 选项，选项不参与地址校验。
        """
        m = re.search(r"\s*,\s*(?=\{)", text)
        if not m:
            return text, ""
        return text[:m.start()].strip(), text[m.end():].strip()

    def _check_url_option(self, r: EntryResult, option: str, field: str) -> None:
        try:
            parsed = json.loads(option)
        except Exception:
            try:
                parsed = lenient_json_load(option)
            except Exception as e:
                r.add("T-12", "警告",
                      f"{field} 的 JSON 选项无法解析，客户端会静默忽略（AnalyzeUrl.kt:222-230）：{e}")
                return
        if not isinstance(parsed, dict):
            r.add("T-12", "警告", f"{field} 的 JSON 选项不是对象，客户端会静默忽略")

    def _check_name(self, r: EntryResult, src: dict) -> None:
        name = src.get("sourceName")
        if not isinstance(name, str) or not name.strip():
            r.add("T-04", "错误", "sourceName 为空")
            return
        name = name.strip()
        if not self.name_re.fullmatch(name):
            r.add("T-04", "错误", f"sourceName 含换行/制表/控制字符：{name!r}")
        lo, hi = self.limits["nameMin"], self.limits["nameMax"]
        if not (lo <= len(name) <= hi):
            r.add("T-04", "警告", f"sourceName 长度 {len(name)} 不在 {lo}–{hi}")
        if self.adult_kw_re.search(name):
            self._adult(r, f"订阅源名命中成人关键词：{name}", "sourceName")

    def _check_group(self, r: EntryResult, src: dict) -> None:
        group = src.get("sourceGroup")
        if group is None or (isinstance(group, str) and not group.strip()):
            r.add("T-05", "警告", "sourceGroup 为空（客户端按未分组显示，字段可空）")
            return
        if not isinstance(group, str):
            return
        if any(ch in group for ch in "\r\n\t"):
            r.add("T-05", "错误", "sourceGroup 含换行/制表符，客户端按 [,;，；] 拆分后不可辨识")
        groups = split_groups(group, self.cfg["groupSeparators"])
        if not groups:
            r.add("T-05", "警告", "sourceGroup 拆分后为空（只含分隔符）")
        if len(groups) > self.limits["maxGroups"]:
            r.add("T-05", "警告", f"分组数 {len(groups)} 超过 {self.limits['maxGroups']}，建议拆包")
        dup = sorted({g for g in groups if groups.count(g) > 1})
        if dup:
            r.add("T-05", "警告", "分组内重复名称：" + "、".join(dup))
        allowed = self.cfg.get("allowedGroups")
        if allowed:
            unknown = [g for g in groups if g not in allowed]
            if unknown:
                r.add("T-05", "错误",
                      "分组不在白名单（白名单见规则 allowedGroups）：" + "、".join(unknown))
        if self.adult_group_re.search(group):
            self._adult(r, f"分组命中成人关键词：{group}", "sourceGroup")

    def _check_numbers(self, r: EntryResult, src: dict) -> None:
        style = src.get("articleStyle")
        if isinstance(style, int) and not isinstance(style, bool):
            if style not in (0, 1, 2):
                r.add("T-06", "警告",
                      f"articleStyle={style} 越界，客户端按默认样式显示（RssArticlesFragment.kt:51-55）")
        rate = src.get("concurrentRate")
        if isinstance(rate, str) and rate.strip() and rate.strip() != "0":
            if not re.fullmatch(r"\d+\s*/\s*\d+|\d+", rate.strip()):
                r.add("T-06", "警告",
                      f"concurrentRate={rate!r} 无法解析为「次数/毫秒」或整数毫秒，"
                      "客户端异常后按不限速处理（ConcurrentRateLimiter.kt:21/54-72）")
        last = src.get("lastUpdateTime")
        if isinstance(last, int) and not isinstance(last, bool):
            if last and not (10 ** 12 <= last < 10 ** 14):
                r.add("T-06", "警告", f"lastUpdateTime={last} 不像 13 位毫秒时间戳")

    def _check_sort_url(self, r: EntryResult, src: dict) -> None:
        raw = src.get("sortUrl")
        if raw is None:
            return
        if not isinstance(raw, str):
            return
        text = raw.strip()
        if not text:
            return
        lower = text.lower()
        if lower.startswith(("@js:", "<js>")):
            if lower.startswith("<js>") and not lower.rstrip().endswith("</js>"):
                r.add("T-07", "错误",
                      "sortUrl 的 <js> 未闭合，客户端按 lastIndexOf('<') 截断会抛异常"
                      "（RssSourceExtensions.kt:23-37）")
            if len(text) > self.limits["inlineJsMax"]:
                r.add("T-13", "警告",
                      f"sortUrl 内联 JS {len(text)} 字符，超过 {self.limits['inlineJsMax']}")
            return
        lines = [s.strip() for s in re.split(r"(?:&&|\r?\n)+", text) if s.strip()]
        if len(lines) > self.limits["sortLinesMax"]:
            r.add("T-07", "警告", f"分类行 {len(lines)} 条，超过 {self.limits['sortLinesMax']}")
        names: list[str] = []
        bad_urls: list[str] = []
        for i, line in enumerate(lines, start=1):
            title, sep, url = line.partition("::")
            title = title.strip()
            url = url.strip() if sep else line.strip()
            if sep and not title:
                r.add("T-07", "警告", f"分类第 {i} 行名称为空：{line}")
            if sep and not url:
                r.add("T-07", "警告",
                      f"分类「{title or i}」url 为空，客户端会跳过该行（RssSourceExtensions.kt:39-48）")
                continue
            if not sep:
                if url.startswith("//") or url.startswith("#"):
                    r.add("T-07", "警告",
                          f"分类第 {i} 行像注释（{url[:30]}），但客户端会把它当作分类地址"
                          "（RssSourceExtensions.kt:39-49），建议删除或在行首加名称::")
                    continue
                if not re.match(r"^(?:https?://|/|{{|@js:|<js>|\\$)", url, re.I):
                    r.add("T-07", "警告",
                          f"分类第 {i} 行既没有 :: 分隔，也不像地址：{url[:40]}")
            if sep and title:
                names.append(title)
            base, option = self._split_url_option(url)
            if option:
                self._check_url_option(r, option, f"sortUrl 第 {i} 行")
            if base.startswith("{{") or base.lower().startswith(("@js:", "<js>")):
                continue
            if base.startswith("//"):
                r.add("T-07", "警告",
                      f"分类第 {i} 行地址是 // 开头的协议相对形式，拼接后多一个斜杠：{base[:40]}")
                continue
            if "://" in base and not base.lower().startswith(("http://", "https://")):
                bad_urls.append(base)
        if bad_urls:
            r.add("T-07", "错误", "分类地址只允许 http/https 或相对路径：" + "、".join(bad_urls[:5]))
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            r.add("T-07", "警告", "分类名称重复：" + "、".join(dup))
        if src.get("singleUrl") is True and len(lines) > 1:
            r.add("T-07", "错误",
                  "singleUrl=true 且 sortUrl 配了多条分类：客户端只取首个 :: 之后的整段文本"
                  "（RssViewModel.kt:67-71），多行会粘连成无效地址")
        if self.adult_kw_re.search(" ".join(names)):
            self._adult(r, "分类名称命中成人关键词", "sortUrl")

    def _check_rules(self, r: EntryResult, src: dict) -> None:
        articles = src.get("ruleArticles")
        has_list = isinstance(articles, str) and bool(articles.strip())
        if not has_list:
            others = [k for k in self.cfg["ruleFields"] if k != "ruleArticles"
                      and isinstance(src.get(k), str) and src[k].strip()]
            if others:
                r.add("T-08", "警告",
                      "ruleArticles 为空，其余规则不会生效（客户端改走默认 XML 解析，"
                      "RssParserByRule.kt:39-42、RssParserDefault.kt:36-113）：" + "、".join(others))
            return
        if not isinstance(src.get("ruleTitle"), str) or not src["ruleTitle"].strip():
            r.add("T-08", "错误",
                  "ruleTitle 为空：列表项标题取空后会被丢弃（RssParserByRule.kt:127-129）")
        if not isinstance(src.get("ruleLink"), str) or not src["ruleLink"].strip():
            r.add("T-08", "警告",
                  "ruleLink 为空：文章链接回落为源地址（RssParserByRule.kt:125）")

    def _check_rule_syntax(self, r: EntryResult, src: dict) -> None:
        list_fields = set(self.cfg["listRuleFields"])
        for field in self.cfg["ruleFields"]:
            value = src.get(field)
            for level, msg in check_rule_syntax(value, field, field in list_fields):
                if msg == "{{ }} 未配对":
                    continue  # 共用检查按个数比较，JS 里的 }} 会误报；改用下方按序扫描
                r.add("T-10", level, f"{field}：{msg}")
            leftover = self._unclosed_inner_rule(value)
            if leftover:
                r.add("T-10", "错误", f"{field}：{leftover}")

    @staticmethod
    def _unclosed_inner_rule(value: Any) -> str:
        """按序配对 {{...}}，只报「有开无闭」。

        依据 AppPattern.EXP_PATTERN（AppPattern.kt:9）：内嵌规则只在 {{ 与 }} 成对时匹配，
        单个 }} 属于 JS 对象右括号，不构成缺陷。
        """
        if not isinstance(value, str) or "{{" not in value:
            return ""
        text = value
        pattern = re.compile(r"\{\{[\w\W]*?\}\}")
        while True:
            new = pattern.sub("", text)
            if new == text:
                break
            text = new
        if "{{" in text:
            pos = text.index("{{")
            return f"{{{{ 未闭合：{text[pos:pos + 40]!r}"
        return ""

    def _check_json_fields(self, r: EntryResult, src: dict) -> None:
        header = src.get("header")
        if isinstance(header, str) and header.strip():
            low = header.strip().lower()
            if not low.startswith(("@js:", "<js>")):
                try:
                    parsed = json.loads(header)
                    if not isinstance(parsed, dict):
                        r.add("T-12", "错误", "header 不是 JSON 对象")
                except Exception:
                    try:
                        parsed = lenient_json_load(header)
                        if isinstance(parsed, dict):
                            r.add("T-12", "警告",
                                  "header 非严格 JSON（单引号/裸键/尾逗号），客户端可宽松解析但会记日志"
                                  "（BaseSource.kt:115-120），建议改为严格 JSON")
                        else:
                            r.add("T-12", "错误", "header 不是 JSON 对象")
                    except Exception as e:
                        r.add("T-12", "错误", f"header 无法解析为 JSON 对象：{e}")
            elif low.startswith("<js>") and not low.rstrip().endswith("</js>"):
                r.add("T-12", "错误", "header 的 <js> 未闭合")
        ui = src.get("loginUi")
        if isinstance(ui, str) and ui.strip():
            low = ui.strip().lower()
            if not low.startswith(("@js:", "<js>")):
                try:
                    if not isinstance(json.loads(ui), list):
                        r.add("T-12", "警告", "loginUi 不是 JSON 数组，客户端解析失败时返回空")
                except Exception as e:
                    r.add("T-12", "警告", f"loginUi 无法解析为 JSON 数组：{e}")
        lib = src.get("jsLib")
        if isinstance(lib, str) and lib.strip().startswith("{"):
            try:
                if not isinstance(json.loads(lib), dict):
                    r.add("T-12", "警告", "jsLib 以 { 开头但不是 JSON 对象")
            except Exception as e:
                r.add("T-12", "警告", f"jsLib 无法解析为 JSON 对象：{e}")

    def _check_credentials(self, r: EntryResult, src: dict) -> None:
        parts = [v for v in src.values() if isinstance(v, str)]
        m = self.cred_re.search("\n".join(parts))
        if m:
            r.add("T-11", "错误", f"字段中出现疑似写死凭证/手机号：{m.group(0)[:40]}")

    def _check_sizes(self, r: EntryResult, src: dict) -> None:
        size = len(json.dumps(src, ensure_ascii=False).encode("utf-8"))
        if size > self.limits["entryMax"]:
            r.add("T-13", "警告", f"单条体积 {size} 字节，超过 {self.limits['entryMax']}")
        lib = src.get("jsLib")
        if isinstance(lib, str) and len(lib.encode("utf-8")) > self.limits["jsLibMax"]:
            r.add("T-13", "错误", f"jsLib 体积超过 {self.limits['jsLibMax']} 字节")

    def _check_adult(self, r: EntryResult, src: dict) -> None:
        own_host = host_last2(_host_of(src.get("sourceUrl")))
        parts = [v for v in src.values() if isinstance(v, str)]
        for host in re.findall(r"https?://([A-Za-z0-9.-]+)", "\n".join(parts)):
            last2 = host_last2(host)
            if last2 == own_host:
                continue
            if last2 in self.adult_domains or host.lower() in self.adult_domains:
                self._adult(r, f"字段内引用 18+ 名单域名：{host}", "字段内 URL")

    # ---------- 探活 ----------
    def probe(self, loaded: list[LoadedJSON], results: list[EntryResult],
              limit: int = 0) -> list[dict]:
        cfg = self.cfg.get("探活", {})
        if not cfg.get("启用", False):
            return []
        cap = limit or int(cfg.get("采样上限", 10))
        targets: dict[tuple[str, int], dict] = {}
        for lj in loaded:
            if isinstance(lj.data, list):
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
            url, reason = self._probe_url(src)
            if not url:
                r.probe = ProbeResult("跳过", "C", 0, reason)
                done += 1
                continue
            headers = self._probe_headers(src, cfg)
            res = probe_api.request_with_retry(
                url, headers=headers, timeout=float(cfg.get("总超时秒", 12)),
                retries=int(cfg.get("重试", 1)),
                interval=float(cfg.get("重试间隔秒", 1)))
            feed = self._feed_hit(res.get("text", ""), cfg)
            rules = bool(isinstance(src.get("ruleArticles"), str)
                         and src["ruleArticles"].strip())
            ep = {"名称": "分类首页", "URL": url, "状态码": res["status"],
                  "耗时毫秒": res["elapsed_ms"], "结论": "", "说明": ""}
            if res["status"] == 200 and res["bytes"] >= int(cfg.get("最小响应字节", 200)):
                if feed:
                    r.probe = ProbeResult(
                        "通过", "C", res["elapsed_ms"],
                        f"分类页可达且响应含 XML/RSS 特征（{res['bytes']} 字节，{res['elapsed_ms']}ms）；"
                        "列表规则未执行，按待复核记 C", [ep])
                    ep.update({"结论": "通过", "说明": "响应含 XML/RSS 特征"})
                elif not rules:
                    r.probe = ProbeResult(
                        "跳过", "C", res["elapsed_ms"],
                        f"分类页可达（{res['bytes']} 字节，{res['elapsed_ms']}ms），但响应非 XML 特征且 "
                        "ruleArticles 为空：默认解析器只认 item 标签（RssParserDefault.kt:36-113），"
                        "判定为疑似规则写错，而非站点不可用", [ep])
                    ep.update({"结论": "跳过", "说明": "非 XML 且无列表规则"})
                else:
                    r.probe = ProbeResult(
                        "通过", "C", res["elapsed_ms"],
                        f"分类页可达（{res['bytes']} 字节，{res['elapsed_ms']}ms）；"
                        "ruleArticles 已配置，规则解析未执行，记 C", [ep])
                    ep.update({"结论": "通过", "说明": "网络段通过，规则未执行"})
            elif res["status"] == 200:
                r.probe = ProbeResult(
                    "跳过", "C", res["elapsed_ms"],
                    f"HTTP 200 但响应仅 {res['bytes']} 字节，无法确认有效，记 C", [ep])
                ep.update({"结论": "跳过", "说明": "响应过短"})
            elif res["status"] in (401, 403, 429):
                r.probe = ProbeResult(
                    "跳过", "C", res["elapsed_ms"],
                    f"HTTP-{res['status']}：疑似反爬/需登录，无法判定站点可用性（非规则写错）", [ep])
                ep.update({"结论": "跳过", "说明": "疑似反爬/需登录"})
            elif res["status"] == 404:
                r.probe = ProbeResult(
                    "失败", "D", res["elapsed_ms"],
                    "HTTP-404：分类地址 404，多为 sortUrl 过期或路径写错（规则侧）", [ep])
                ep.update({"结论": "失败", "说明": "404，分类地址可能过期"})
            else:
                detail = res["error"] or f"HTTP-{res['status']}"
                r.probe = ProbeResult(
                    "失败", "D", res["elapsed_ms"], f"站点侧失败：{detail}", [ep])
                ep.update({"结论": "失败", "说明": detail})
            r.probe.endpoints = [ep]
            done += 1
        return []

    def _probe_url(self, src: dict) -> tuple[str, str]:
        raw_sort = src.get("sortUrl")
        if isinstance(raw_sort, str) and raw_sort.strip():
            text = raw_sort.strip()
            low = text.lower()
            if low.startswith(("@js:", "<js>")):
                return "", "sortUrl 为 JS 驱动，静态无法构造分类地址"
            lines = [s.strip() for s in re.split(r"(?:&&|\r?\n)+", text) if s.strip()]
            if lines:
                first = lines[0]
                _, sep, url = first.partition("::")
                url = url.strip() if sep else first
                if url.startswith("{{"):
                    return "", "分类地址含变量，静态无法构造"
                return self._absolute(url, src.get("sourceUrl"))
        base = src.get("sourceUrl")
        if isinstance(base, str) and base.strip():
            text = base.strip()
            if text.lower().startswith(("@js:", "<js>")):
                return "", "sourceUrl 为 JS 驱动，静态无法构造探活地址"
            return self._split_url_option(text)[0], ""
        return "", "sourceUrl 为空，无法构造探活地址"

    @staticmethod
    def _absolute(url: str, base: Any) -> tuple[str, str]:
        if not isinstance(url, str) or not url.strip():
            return "", "分类地址为空"
        url = url.strip()
        if url.lower().startswith(("http://", "https://")):
            return url, ""
        if url.startswith("{{"):
            return "", "分类地址含变量，静态无法构造"

    def _probe_headers(self, src: dict, cfg: dict) -> dict:
        headers: dict[str, str] = {"User-Agent": cfg.get("请求头UA", probe_api.UA)}
        raw = src.get("header")
        if not isinstance(raw, str) or not raw.strip():
            return headers
        if raw.strip().lower().startswith(("@js:", "<js>")):
            return headers
        for loader in (json.loads, lenient_json_load):
            try:
                parsed = loader(raw)
            except Exception:
                continue
            if isinstance(parsed, dict):
                headers.update({str(k): str(v) for k, v in parsed.items()})
                break
        return headers

    def _feed_hit(self, text: str, cfg: dict) -> bool:
        head = (text or "")[:2000].lower()
        return any(token.lower() in head for token in cfg.get("feed识别", []))

    # ---------- 修复 / 补充 ----------
    def build_plan(self, loaded: list[LoadedJSON], do_repair: bool = True,
                   do_supplement: bool = True) -> RepairPlan:
        plan = RepairPlan()
        plan.original = {lj.path: copy.deepcopy(lj.data) for lj in loaded}
        plan.data = {lj.path: copy.deepcopy(lj.data) for lj in loaded}
        fix_cfg = self.cfg.get("修复", {})
        sup_cfg = self.cfg.get("补充", {})
        fixes = set(fix_cfg.get("启用动作", [])) if do_repair else set()
        sups = set(sup_cfg.get("启用动作", [])) if do_supplement else set()

        for lj in loaded:
            data = plan.data[lj.path]
            if not isinstance(data, list):
                continue
            orders = [s.get("customOrder") for s in data
                      if isinstance(s, dict) and isinstance(s.get("customOrder"), int)
                      and not isinstance(s.get("customOrder"), bool)]
            duplicate_order = len(orders) != len(set(orders))

            for idx, src in enumerate(data, start=1):
                if not isinstance(src, dict):
                    continue
                name = src.get("sourceName") if isinstance(src.get("sourceName"), str) else ""
                if "F-01" in fixes:
                    self._fix_style(plan, lj.path, idx, name, src, fix_cfg)
                if "F-03" in fixes:
                    self._fix_sort(plan, lj.path, idx, name, src)
                if "F-04" in fixes:
                    self._fix_trim(plan, lj.path, idx, name, src, fix_cfg)
                if "F-05" in fixes:
                    self._fix_header(plan, lj.path, idx, name, src)
                if "F-06" in fixes:
                    self._fix_trailing_slash(plan, lj.path, idx, name, src, fix_cfg)
                if "S-01" in sups:
                    self._sup_comment(plan, lj.path, idx, name, src, sup_cfg)
                if "S-02" in sups:
                    self._sup_group(plan, lj.path, idx, name, src, sup_cfg)
                if "S-03" in sups:
                    self._sup_icon(plan, lj.path, idx, name, src, sup_cfg)

                self._note_manual(plan, lj.path, idx, name, src)

            if "F-02" in fixes and duplicate_order:
                for idx, src in enumerate(data, start=1):
                    if not isinstance(src, dict):
                        continue
                    name = src.get("sourceName") if isinstance(src.get("sourceName"), str) else ""
                    self._fix_order(plan, lj.path, idx, name, src, idx - 1)
        return plan

    def _fix_style(self, plan: RepairPlan, file: str, idx: int, name: str,
                   src: dict, cfg: dict) -> None:
        style = src.get("articleStyle")
        if isinstance(style, int) and not isinstance(style, bool) and style not in (0, 1, 2):
            default = int(cfg.get("articleStyle默认", 0))
            src["articleStyle"] = default
            plan.add("F-01", "修复", file, idx, name, "articleStyle", style, default,
                     "越界取值客户端会走默认样式（RssArticlesFragment.kt:51-55），归 0")

    def _fix_sort(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        raw = src.get("sortUrl")
        if not isinstance(raw, str) or not raw.strip():
            return
        if raw.strip().lower().startswith(("@js:", "<js>")):
            return
        lines = [s.strip() for s in re.split(r"(?:&&|\r?\n)+", raw) if s.strip()]
        new = "\n".join(lines)
        if new != raw:
            src["sortUrl"] = new
            plan.add("F-03", "修复", file, idx, name, "sortUrl", raw, new,
                     "去掉空白行与行尾空白，保持 name::url 语义不变（RssSourceExtensions.kt:39-49）")

    def _fix_trim(self, plan: RepairPlan, file: str, idx: int, name: str,
                  src: dict, cfg: dict) -> None:
        for key in cfg.get("裁剪空白字段", []):
            value = src.get(key)
            if isinstance(value, str) and value != value.strip():
                new = value.strip()
                src[key] = new
                plan.add("F-04", "修复", file, idx, name, key, value, new, "裁掉首尾空白字符")

    def _fix_header(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        raw = src.get("header")
        if not isinstance(raw, str) or not raw.strip():
            return
        if raw.strip().lower().startswith(("@js:", "<js>")):
            return
        try:
            json.loads(raw)
            return
        except Exception:
            pass
        try:
            parsed = lenient_json_load(raw)
        except Exception:
            return
        if not isinstance(parsed, dict):
            return
        new = json.dumps(parsed, ensure_ascii=False)
        src["header"] = new
        plan.add("F-05", "修复", file, idx, name, "header", raw, new,
                 "把宽松 JSON（单引号/裸键/尾逗号）改写为严格 JSON（BaseSource.kt:115-120）")

    def _fix_trailing_slash(self, plan: RepairPlan, file: str, idx: int, name: str,
                            src: dict, cfg: dict) -> None:
        for key in cfg.get("去尾斜杠字段", []):
            value = src.get(key)
            if not isinstance(value, str):
                continue
            path = urllib.parse.urlparse(value.strip()).path
            if value.endswith("/") and path in ("", "/"):
                new = value.rstrip("/")
                if new and "://" in new:
                    src[key] = new
                    plan.add("F-06", "修复", file, idx, name, key, value, new,
                             "去掉主机级尾斜杠，绝对化与拼接结果不变")

    def _fix_order(self, plan: RepairPlan, file: str, idx: int, name: str,
                   src: dict, order: int) -> None:
        old = src.get("customOrder")
        if isinstance(old, int) and not isinstance(old, bool) and old != order:
            src["customOrder"] = order
            plan.add("F-02", "修复", file, idx, name, "customOrder", old, order,
                     "批内 customOrder 重复，按出现顺序重排为 0..n-1")

    def _sup_comment(self, plan: RepairPlan, file: str, idx: int, name: str,
                     src: dict, cfg: dict) -> None:
        raw = src.get("sourceComment")
        if isinstance(raw, str) and raw.strip() and self.comment_re.search(raw):
            return
        header = cfg.get("注释模板", "来源：待补；基线：{基线}；探活：C；复探：{日期}")
        header = header.replace("{基线}", self.baseline).replace("{日期}", date_text())
        new = header + ("\n" + raw if isinstance(raw, str) and raw.strip() else "")
        src["sourceComment"] = new
        plan.add("S-01", "补充", file, idx, name, "sourceComment",
                 raw if raw is not None else _MISSING, new,
                 "按四段注释模板预填，来源需人工补填", need_confirm=True)

    def _sup_group(self, plan: RepairPlan, file: str, idx: int, name: str,
                   src: dict, cfg: dict) -> None:
        raw = src.get("sourceGroup")
        if isinstance(raw, str) and raw.strip():
            return
        default = cfg.get("默认分组", "待校验")
        src["sourceGroup"] = default
        plan.add("S-02", "补充", file, idx, name, "sourceGroup",
                 raw if raw is not None else _MISSING, default,
                 "分组为空，按规范归入「待校验」（客户端无分组白名单）", need_confirm=True)

    def _sup_icon(self, plan: RepairPlan, file: str, idx: int, name: str,
                  src: dict, cfg: dict) -> None:
        raw = src.get("sourceIcon")
        if isinstance(raw, str) and raw.strip():
            return
        base = src.get("sourceUrl")
        if not isinstance(base, str) or "://" not in base:
            return
        origin = f"{base.split('://', 1)[0]}://{_host_of(base)}"
        new = cfg.get("图标模板", "{源}/favicon.ico").replace("{源}", origin)
        src["sourceIcon"] = new
        plan.add("S-03", "补充", file, idx, name, "sourceIcon",
                 raw if raw is not None else _MISSING, new,
                 "按站点 origin 推断 favicon 地址，未验证可达", need_confirm=True)

    def _note_manual(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        extra = sorted(set(src.keys()) - self.allowed)
        if extra:
            plan.unhandle(file, idx, name, "实体未定义字段：" + "、".join(extra),
                          "删字段属于内容取舍，且可能承载用户备注", "人工确认后再删除或改挂 sourceComment")
        articles = src.get("ruleArticles")
        if isinstance(articles, str) and articles.strip():
            if not (isinstance(src.get("ruleTitle"), str) and src["ruleTitle"].strip()):
                plan.unhandle(file, idx, name, "ruleArticles 已配但 ruleTitle 为空",
                              "标题规则需按站点 DOM 结构编写，无法模板化", "人工补写标题规则")
        raw_header = src.get("header")
        if isinstance(raw_header, str) and raw_header.strip():
            low = raw_header.strip().lower()
            if not low.startswith(("@js:", "<js>")):
                try:
                    json.loads(raw_header)
                except Exception:
                    try:
                        if not isinstance(lenient_json_load(raw_header), dict):
                            raise ValueError
                    except Exception:
                        plan.unhandle(file, idx, name, "header 无法解析为 JSON 对象",
                                      "需核对站点请求头原文", "人工改写为严格 JSON 或删除 header")
        if self._adult_hits(src) and self.adult_mode == "阻断":
            plan.unhandle(file, idx, name,
                          "成人内容命中公开域：" + "、".join(self._adult_hits(src)),
                          "内容判断类，工具不自动删除或改分组",
                          "移入私有域（--域 私有）或私有订阅源包")

    def _adult_hits(self, src: dict) -> list[str]:
        hits: list[str] = []
        name = src.get("sourceName")
        if isinstance(name, str) and self.adult_kw_re.search(name):
            hits.append(f"源名：{name}")
        group = src.get("sourceGroup")
        if isinstance(group, str) and self.adult_group_re.search(group):
            hits.append(f"分组：{group}")
        host = _host_of(src.get("sourceUrl"))
        if host and (host_last2(host) in self.adult_domains or host in self.adult_domains):
            hits.append(f"域名：{host}")
        parts = [v for v in src.values() if isinstance(v, str)]
        own = host_last2(host)
        for h in re.findall(r"https?://([A-Za-z0-9.-]+)", "\n".join(parts)):
            if host_last2(h) == own:
                continue
            if host_last2(h) in self.adult_domains or h.lower() in self.adult_domains:
                hits.append(f"引用域名：{h}")
        return hits


def load_rules(path: str) -> dict:
    return json.load(open(path, "r", encoding="utf-8-sig"))
