"""TVBox 配置适配器。

检查项对应《TVBox 源规范》TVB-NAM / TVB-CFG / TVB-SEC 各段。
T-09 按 rules 的「域」开关执行：公开域命中成人内容判不通过；私有域只打标
「成人域」并向收敛曝光字段（searchable/quickSearch/changeable=0）补充，不阻断。

探活说明：TVBox 规范未单列探活章节，maccms 端点/超时/重试/采样沿用
《小猫影视源规范》CAT-PRB-002/003；jar/js/py 与本地路径只判可达或跳过，契约不执行。
"""

from __future__ import annotations

import base64
import copy
import json
import os
import re
from typing import Any

from core import EntryResult, LoadedJSON, ProbeResult, load_json_strict
from repair import RepairPlan, _MISSING
import probe as probe_api


def host_last2(host: str) -> str:
    parts = [p for p in host.lower().split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def _host_of(url: Any) -> str:
    if not isinstance(url, str) or "://" not in url:
        return ""
    return url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].lower()


def _origin(url: str) -> str:
    m = re.match(r"(?i)(https?://[^/]+)", url)
    return m.group(1) if m else ""


def _loader(api: str, type_value: Any) -> str:
    low = api.lower()
    if ".js" in low:
        return "js"
    if ".py" in low:
        return "py"
    if "csp_" in low:
        return "jar"
    if low.startswith(("http://", "https://")):
        return "cms" if type_value in (0, 1) else "url"
    if api.startswith("./") or api.startswith("../"):
        return "local"
    return "unknown"


def _iter_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_iter_strings(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(_iter_strings(v))
    return out


class TVBoxAdapter:
    name = "TVBox"
    tool_name = "源检测·TVBox"
    suite = "TVBoxP0"
    baseline = "TVBox 源规范（TVB-NAM / TVB-CFG / TVB-SEC）"
    implemented = True

    def __init__(self, rules: dict, domain: str = ""):
        self.cfg = rules
        self.key_re = re.compile(rules["keyRegex"])
        self.name_kw_re = re.compile(rules["adultKeywordRegex"], re.I)
        self.adult_domains = self._load_18plus(rules.get("adultDomainListPath", ""))
        self.adult_domains |= {d.lower() for d in rules.get("adultDomainSupplement", [])}
        self.domain = domain or rules.get("域", {}).get("默认", "公开")
        self.adult_mode = rules.get("域", {}).get("取值", {}).get(self.domain, "阻断")

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

    def coverage(self) -> list[tuple[str, str, str]]:
        return [
            ("T-01", "JSON 可解析、顶层对象、无 BOM、无重复键、非多仓（TVB-CFG-019、TVB-CFG-019）", "自动"),
            ("T-02", "sites 存在且为数组、条目为对象（TVB-CFG-019/TVB-CFG-001）", "自动"),
            ("T-03", "key 必填、字符集/长度合规、批内唯一、非 push_agent（TVB-NAM-005）", "自动"),
            ("T-04", "key 形态前缀与 type 对应（TVB-NAM-005）", "自动"),
            ("T-05", "type 必填且为数字 0/1/3/4（TVB-CFG-001）", "自动"),
            ("T-06", "api 必填、形态与 type 一致、禁止双层包名/多点 py（TVB-CFG-003、TVB-CFG-002）", "自动"),
            ("T-07", "name 命名合规、无禁用分隔符、批内不重名（TVB-NAM-017/TVB-NAM-016）", "自动"),
            ("T-08", "数字字段为 JSON 数字且取值合规（TVB-CFG-001/TVB-CFG-031）", "自动"),
            ("T-09", "成人内容识别与打标；公开域阻断、私有域只打标并收敛曝光", "自动+名单"),
            ("T-10", "禁用/自造字段（filterable、loader、未知 site 键、未读顶层键）", "自动"),
            ("T-11", "ext 形态与 v/base/键名/路径合规（TVB-CFG-028）", "自动"),
            ("T-12", "parses 必填 name/url/ext/type（TVB-CFG-031）", "自动"),
            ("T-13", "lives 必填 name/type 字符串及 url/api（TVB-CFG-012）", "自动"),
            ("T-14", "flags 为字符串数组、元素命名同族（TVB-CFG-031）", "自动"),
            ("T-15", "spider 写法 ;md5; 与 32 位小写 md5（TVB-NAM-015/TVB-NAM-014）", "自动"),
            ("T-16", "重复 api、同 key 双实现等线路风险（TVB-NAM-005）", "自动"),
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
        seen_keys: dict[str, list[EntryResult]] = {}
        seen_names: dict[str, list[EntryResult]] = {}
        seen_api: dict[str, list[EntryResult]] = {}

        for lj in loaded:
            path, data = lj.path, lj.data
            if lj.has_bom:
                global_errors.append({"文件": path, "说明": "警告：文件带 UTF-8 BOM，不符合 TVB-CFG-019"})
            if lj.duplicate_keys:
                keys = "、".join(sorted(set(lj.duplicate_keys)))
                global_errors.append({"文件": path, "说明": f"JSON 存在重复键：{keys}（TVB-CFG-019，后者覆盖前者）"})
            if not isinstance(data, dict):
                global_errors.append({"文件": path, "说明": "顶层不是 JSON 对象，不符合 TVBox 配置形态"})
                continue
            if "storeHouse" in data and "sites" not in data:
                global_errors.append({"文件": path, "说明": "多仓（storeHouse）格式暂不支持，请先展开为单仓 api.json"})
                continue
            sites = data.get("sites")
            if not isinstance(sites, list):
                global_errors.append({"文件": path, "说明": "缺少 sites 数组，客户端会整份加载失败（TVB-CFG-019）"})
                continue

            unknown_top = [k for k in data.keys()
                           if k not in self.cfg["顶层字段允许"] and k not in self.cfg["顶层字段禁用"]]
            if unknown_top:
                global_errors.append({"文件": path,
                                      "说明": "警告：存在客户端不读取的顶层字段：" + "、".join(sorted(unknown_top)) + "（TVB-CFG-031）"})
            for key in self.cfg["顶层字段禁用"]:
                if key in data:
                    global_errors.append({"文件": path, "说明": f"顶层禁用字段 {key}"})

            for idx, src in enumerate(sites, start=1):
                r = self._analyze(path, idx, src)
                results.append(r)
                if isinstance(src, dict):
                    key = src.get("key")
                    name = src.get("name")
                    api = src.get("api")
                    if isinstance(key, str) and key:
                        seen_keys.setdefault(key, []).append(r)
                    if isinstance(name, str) and name:
                        seen_names.setdefault(name, []).append(r)
                    if isinstance(api, str) and api:
                        signature = api + "||" + json.dumps(src.get("ext"), ensure_ascii=False, sort_keys=True)
                        seen_api.setdefault(signature, []).append(r)

        for key, group in seen_keys.items():
            if len(group) > 1:
                for r in group:
                    r.add("T-03", "错误", f"key 在批内重复 {len(group)} 次：{key}（后者覆盖前者，TVB-NAM-005）")
        for name, group in seen_names.items():
            if len(group) > 1:
                for r in group:
                    r.add("T-07", "错误", f"name 在批内重复 {len(group)} 次：{name}（TVB-NAM-017）")
        for signature, group in seen_api.items():
            if len(group) > 1:
                api = signature.split("||", 1)[0]
                for r in group:
                    r.add("T-16", "警告", f"站点 api 与 ext 完全相同（{len(group)} 条）：{api[:40]}，"
                                         f"同实现多 key 会被跳过预热（TVB-NAM-005）")
        return results, global_errors

    def _analyze(self, path: str, idx: int, src: Any) -> EntryResult:
        if not isinstance(src, dict):
            r = EntryResult(path, idx, f"(第{idx}项非对象)", "", None, self.domain)
            r.add("T-02", "错误", "站点条目不是 JSON 对象（TVB-CFG-019）")
            return r
        key = src.get("key") if isinstance(src.get("key"), str) else ""
        name = src.get("name") if isinstance(src.get("name"), str) else key
        api = src.get("api") if isinstance(src.get("api"), str) else ""
        r = EntryResult(path, idx, name, api, src.get("type"), self.domain)

        self._check_key(r, src, key)
        self._check_type(r, src)
        self._check_api(r, src, key, api)
        self._check_name(r, src, key, name)
        self._check_numbers(r, src)
        self._check_fields(r, src)
        self._check_ext(r, src, api)
        self._check_parses(r, src.get("parses"))
        self._check_lives(r, src.get("lives"))
        self._check_flags(r, src.get("flags"))
        self._check_spider(r, src.get("spider"))
        self._check_adult(r, src)
        r.checks_run = len(self.coverage())
        return r

    def _check_key(self, r: EntryResult, src: dict, key: str) -> None:
        raw = src.get("key")
        if not key:
            r.add("T-03", "错误", "key 缺失或为空，整条站点会被静默跳过（TVB-NAM-005）")
            return
        if not isinstance(raw, str):
            r.add("T-03", "错误", f"key 应为字符串，实际 {type(raw).__name__}")
        if not self.key_re.fullmatch(key):
            r.add("T-03", "错误", f"key 不符合 ^[a-z][a-z0-9_]{{2,31}}$：{key}（TVB-NAM-005）")
        if key in self.cfg.get("禁用key", []):
            r.add("T-03", "错误", f"key 使用保留值 {key}（TVB-NAM-005）")

        t = src.get("type")
        prefix_cfg = self.cfg.get("key前缀", {})
        prefixes = prefix_cfg.get(str(t), [])
        if prefixes and not any(key.startswith(p) for p in prefixes):
            r.add("T-04", "警告", f"key 前缀与 type={t} 不匹配，建议 {'/'.join(prefixes)}（TVB-NAM-005）")

    def _check_type(self, r: EntryResult, src: dict) -> None:
        t = src.get("type")
        if t is None:
            r.add("T-05", "错误", "type 缺失，整条站点会被静默跳过（TVB-CFG-001）")
            return
        if isinstance(t, bool) or not isinstance(t, int):
            r.add("T-05", "错误", f"type 必须写 JSON 数字，实际 {type(t).__name__}（TVB-CFG-001）")
            return
        if t not in self.cfg["type允许"]:
            r.add("T-05", "错误", f"type 只允许 0/1/3/4，实际 {t}")

    def _check_api(self, r: EntryResult, src: dict, key: str, api: str) -> None:
        raw = src.get("api")
        if not api:
            r.add("T-06", "错误", "api 缺失或为空，整条站点会被静默跳过（TVB-CFG-001）")
            return
        if not isinstance(raw, str):
            r.add("T-06", "错误", f"api 应为字符串，实际 {type(raw).__name__}")
        low = api.lower()
        if "csp_com.github.catvod.spider." in low:
            r.add("T-06", "错误", "api 写成双层包名 csp_com.github.catvod.spider.X，会 ClassNotFound（TVB-CFG-003）")
        if "csp_" in low:
            cls = api[api.find("csp_") + 4:]
            if "." in cls:
                r.add("T-06", "错误", f"csp_ 之后不允许出现点号：{cls}（TVB-CFG-003）")
            if not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", cls):
                r.add("T-06", "警告", f"类名建议大驼峰且以 Spider 结尾：{cls}（TVB-CFG-003）")
        if ".js" in low and not (low.endswith(".js") or ".js?" in low):
            r.add("T-06", "错误", "api 含 .js 但不是 .js 结尾/`.js?`，会被判成 jar 分支（TVB-CFG-002）")
        if ".py" in low and ".js" in low:
            r.add("T-06", "错误", "api 同时含 .js 与 .py，按判断顺序会走 js，py 永不加载（TVB-CFG-002）")
        if ".py" in low:
            name_part = low.split("?", 1)[0].rsplit("/", 1)[-1]
            if name_part.count(".") > 1:
                r.add("T-06", "错误", f"py 文件名含多个点：{name_part}，模块名会被截断（TVB-CFG-002）")
        if "://" in low and not low.startswith(("http://", "https://")):
            r.add("T-06", "错误", f"api 只允许 http/https/相对路径，实际 {api[:32]}")
        if low.startswith("/"):
            r.add("T-06", "警告", "api 以 / 开头，客户端按相对路径解析，建议写 ./ 起（TVB-NAM-014）")

        loader = _loader(api, src.get("type"))
        t = src.get("type")
        if t in (0, 1) and loader not in ("cms", "url", "unknown"):
            r.add("T-06", "警告", f"type={t} 的 api 看起来是 {loader} 资源，形态与 type 不一致")
        if t == 3 and loader in ("cms",):
            r.add("T-06", "警告", "type=3 的 api 是 CMS 地址，形态与 type 不一致")
        if t == 4 and loader != "unknown":
            r.add("T-06", "警告", f"type=4 的 api 看起来是 {loader} 资源，直播源建议 rms_ 形态")
        if loader == "unknown":
            r.add("T-06", "警告", f"api 形态无法识别：{api[:36]}")

    def _check_name(self, r: EntryResult, src: dict, key: str, name: str) -> None:
        raw = src.get("name")
        if raw is None:
            return
        if not isinstance(raw, str):
            r.add("T-07", "错误", f"name 应为字符串，实际 {type(raw).__name__}")
            return
        if raw != raw.strip():
            r.add("T-07", "警告", "name 首尾含空白，客户端会 trim（TVB-NAM-017）")
        text = raw.strip()
        for ch in self.cfg["name禁止字符"]:
            if ch in text:
                r.add("T-07", "错误", f"name 禁用字符 {ch!r}（TVB-NAM-016）")
        lo, hi = self.cfg["name长度"]
        chinese = len(re.findall(r"[\u4e00-\u9fa5]", text))
        if chinese < lo or chinese > hi:
            r.add("T-07", "警告", f"name 中文 {chinese} 字，规范要求 {lo}–{hi} 字（TVB-NAM-017）：{text}")
        if re.search(r"[A-Za-z]{4,}", text):
            r.add("T-07", "警告", "name 含较长英文串，规范要求中文显示名（TVB-NAM-017）")

    def _check_numbers(self, r: EntryResult, src: dict) -> None:
        for field in self.cfg["数字开关字段"]:
            if field not in src:
                continue
            value = src[field]
            if isinstance(value, bool):
                r.add("T-08", "错误", f"{field} 写成布尔，异常被吞后回落默认 1，关不掉（TVB-CFG-031）")
            elif not isinstance(value, int):
                r.add("T-08", "错误", f"{field} 应为 JSON 数字 0/1，实际 {type(value).__name__}")
            elif value not in (0, 1):
                r.add("T-08", "错误", f"{field} 只允许 0/1，实际 {value}")
        for field in self.cfg["数字字段"]:
            if field not in src:
                continue
            value = src[field]
            if isinstance(value, bool) or not isinstance(value, int):
                r.add("T-08", "错误", f"{field} 应为 JSON 数字，实际 {type(value).__name__}（TVB-CFG-001）")
                continue
            if field == "playerType":
                allowed = self.cfg["playerType允许"]
                if value not in allowed and value < 10:
                    r.add("T-08", "错误", f"playerType={value} 只允许 -1/1/2/≥10")
            if field == "timeout" and value != 0:
                lo, hi = self.cfg["timeout范围"]
                if not (lo <= value <= hi):
                    r.add("T-08", "错误", f"timeout={value} 会被 clamp 到 {lo}~{hi}，请直接写合规值（TVB-CFG-031）")
        cats = src.get("categories")
        if cats is not None:
            if not isinstance(cats, list):
                r.add("T-08", "错误", "categories 应为分类名数组（TVB-CFG-029）")
            else:
                bad = [c for c in cats if not isinstance(c, str) or not c]
                if bad:
                    r.add("T-08", "错误", "categories 含非字符串或空元素")

    def _check_fields(self, r: EntryResult, src: dict) -> None:
        allowed = set(self.cfg["sites字段允许"])
        banned = set(self.cfg["sites字段禁用"])
        for field in banned:
            if field in src:
                if field == "filterable":
                    r.add("T-10", "错误", "filterable 在本仓库只写不读，写了无效（TVB-CFG-031）")
                else:
                    r.add("T-10", "错误", f"禁用字段 {field}（TVB-CFG-031）")
        unknown = sorted(set(src.keys()) - allowed - banned)
        if unknown:
            r.add("T-10", "警告", "存在客户端不读取的自造字段：" + "、".join(unknown) + "（TVB-CFG-031）")

    def _check_ext(self, r: EntryResult, src: dict, api: str) -> None:
        if "ext" not in src:
            return
        ext = src["ext"]
        loader = _loader(api, src.get("type"))
        if loader in ("jar", "js"):
            if not isinstance(ext, dict):
                r.add("T-11", "错误", f"{loader} 源的 ext 必须写成对象，实际 {type(ext).__name__}（TVB-CFG-028）")
                return
            v = ext.get("v")
            if v is None:
                r.add("T-11", "警告", "ext 缺结构版本 v（TVB-CFG-028）")
            elif isinstance(v, bool) or not isinstance(v, int) or v < 1:
                r.add("T-11", "错误", f"ext.v 应为 ≥1 的整数，实际 {v!r}（TVB-CFG-028）")
            if "base" not in ext:
                r.add("T-11", "警告", "ext 缺 base 站点根 URL（TVB-CFG-028）")
            for k in ext.keys():
                if not re.fullmatch(r"[a-z][a-z0-9_]*", str(k)):
                    r.add("T-11", "警告", f"ext 键名建议 snake_case 全小写：{k}（TVB-CFG-028）")
            for text in _iter_strings(ext):
                if "./" in text or "../" in text:
                    r.add("T-11", "错误", "ext 内含 ./ 或 ../，配置会被整体替换而损坏（TVB-CFG-028）")
        elif loader == "py":
            if not isinstance(ext, (str, dict)):
                r.add("T-11", "错误", f"py 源 ext 应为字符串，实际 {type(ext).__name__}（TVB-CFG-028）")
            if isinstance(ext, dict):
                r.add("T-11", "错误", "py 源 ext 写成对象，Python 侧按字符串使用（TVB-CFG-028）")
            elif isinstance(ext, str) and ext and not ext.startswith(("http://", "https://")):
                r.add("T-11", "警告", "py 源 ext 建议写完整入口 URL（TVB-CFG-028）")

    def _check_parses(self, r: EntryResult, parses: Any) -> None:
        if parses is None:
            return
        if not isinstance(parses, list):
            r.add("T-12", "错误", "parses 应为数组")
            return
        names: list[str] = []
        for i, p in enumerate(parses, start=1):
            if not isinstance(p, dict):
                r.add("T-12", "错误", f"parses 第 {i} 项不是对象")
                continue
            name = p.get("name")
            if not isinstance(name, str) or not name.strip():
                r.add("T-12", "错误", f"parses 第 {i} 项缺 name")
            else:
                names.append(name)
                if not (2 <= len(name) <= 8):
                    r.add("T-12", "警告", f"parses.name 长度 {len(name)} 不在 2–8：{name}")
            url = p.get("url")
            if not isinstance(url, str) or not url.strip():
                r.add("T-12", "错误", f"parses 第 {i} 项缺 url")
            if "ext" not in p:
                r.add("T-12", "警告", f"parses 第 {i} 项未显式写 \"ext\": {{}}（TVB-CFG-031）")
            elif not isinstance(p["ext"], dict):
                r.add("T-12", "错误", f"parses 第 {i} 项 ext 必须是对象（TVB-CFG-031）")
            t = p.get("type", 0)
            if isinstance(t, bool) or not isinstance(t, int) or t not in (0, 1, 2, 3, 4):
                r.add("T-12", "错误", f"parses 第 {i} 项 type 只允许 0–4")
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            r.add("T-12", "警告", "parses.name 重名：" + "、".join(sorted(dup)))

    def _check_lives(self, r: EntryResult, lives: Any) -> None:
        if lives is None:
            return
        if not isinstance(lives, list):
            r.add("T-13", "错误", "lives 应为数组")
            return
        for i, item in enumerate(lives, start=1):
            if not isinstance(item, dict):
                r.add("T-13", "错误", f"lives 第 {i} 项不是对象")
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                r.add("T-13", "错误", f"lives 第 {i} 项缺 name")
            t = item.get("type")
            if t is None:
                r.add("T-13", "错误", f"lives 第 {i} 项缺 type")
            elif isinstance(t, int) and not isinstance(t, bool):
                r.add("T-13", "错误", f"lives 第 {i} 项 type 写成数字，必须写字符串 \"0\"/\"3\"（TVB-CFG-012）")
            elif not isinstance(t, str) or t.strip() not in ("0", "3"):
                r.add("T-13", "错误", f"lives 第 {i} 项 type 只允许字符串 \"0\"/\"3\"，实际 {t!r}")
            else:
                if t.strip() == "0" and not item.get("url"):
                    r.add("T-13", "错误", f"lives 第 {i} 项 type=\"0\" 必须写 url")
                if t.strip() == "3" and not item.get("api"):
                    r.add("T-13", "错误", f"lives 第 {i} 项 type=\"3\" 必须写 api")

    def _check_flags(self, r: EntryResult, flags: Any) -> None:
        if flags is None:
            return
        if not isinstance(flags, list):
            r.add("T-14", "错误", "flags 必须是字符串数组，写成字符串会静默变空（TVB-CFG-031）")
            return
        bad = [f for f in flags if not isinstance(f, str) or not f]
        if bad:
            r.add("T-14", "错误", "flags 含非字符串或空元素")
        for f in flags:
            if isinstance(f, str) and not re.fullmatch(r"(vip_|parse_)[a-z0-9_]+", f):
                r.add("T-14", "警告", f"flags 元素命名建议 vip_<平台>/parse_<源>：{f}（TVB-CFG-031）")

    def _check_spider(self, r: EntryResult, spider: Any) -> None:
        if spider is None:
            return
        if not isinstance(spider, str):
            r.add("T-15", "错误", "spider 应为字符串")
            return
        text = spider.strip()
        low = text.lower()
        if ";MD5;" in text or re.search(r";md5[^;]", text):
            r.add("T-15", "错误", "spider 的 md5 分隔符必须是小写固定写法 ;md5;（TVB-NAM-015）")
        parts = text.split(";md5;")
        if len(parts) > 1:
            digest = parts[1].strip()
            if not re.fullmatch(r"[0-9a-f]{32}", digest):
                r.add("T-15", "错误", "spider 的 md5 必须是 32 位小写十六进制（TVB-NAM-015）")
        path = parts[0].strip()
        if not path.startswith(("http://", "https://", "./")):
            r.add("T-15", "警告", f"spider 建议写完整 URL 或 ./ 相对路径：{path}（TVB-NAM-014）")

    def _adult_hits(self, src: dict) -> list[str]:
        hits: list[str] = []
        name = src.get("name")
        key = src.get("key")
        if isinstance(name, str) and self.name_kw_re.search(name):
            hits.append(f"name：{name}")
        if isinstance(key, str) and self.name_kw_re.search(key):
            hits.append(f"key：{key}")
        ext = src.get("ext")
        for text in _iter_strings(ext):
            host = _host_of(text)
            if host and (host_last2(host) in self.adult_domains or host in self.adult_domains):
                hits.append(f"ext 域名：{host}")
        api = src.get("api")
        host = _host_of(api)
        if host and (host_last2(host) in self.adult_domains or host in self.adult_domains):
            hits.append(f"api 域名：{host}")
        return hits

    def _check_adult(self, r: EntryResult, src: dict) -> None:
        hits = self._adult_hits(src)
        if not hits:
            return
        r.tag("成人域")
        message = "成人内容：" + "、".join(hits)
        if self.adult_mode == "打标":
            r.add("T-09", "警告", message + "（私有域：仅打标，不阻断）")
            switches = src
            missing = [f for f in self.cfg["数字开关字段"]
                       if switches.get(f) != 0]
            if missing:
                r.add("T-09", "警告",
                      "私有域成人条目建议收敛曝光：" + "、".join(missing) + "=0（TVB-SEC-001）")
        else:
            r.add("T-09", "错误", message + "（公开域：不通过，应移入私有域/私有包）")

    # ---------- 探活 ----------
    def probe(self, loaded: list[LoadedJSON], results: list[EntryResult],
              limit: int = 0) -> list[dict]:
        cfg = self.cfg.get("探活", {})
        if not cfg.get("启用", False):
            return []
        cap = limit or int(cfg.get("站点采样上限", 20))
        targets: dict[tuple[str, int], dict] = {}
        for lj in loaded:
            if not isinstance(lj.data, dict) or not isinstance(lj.data.get("sites"), list):
                continue
            for idx, src in enumerate(lj.data["sites"], start=1):
                if isinstance(src, dict):
                    targets[(lj.path, idx)] = src
        done = 0
        for r in results:
            if done >= cap:
                break
            src = targets.get((r.file, r.index))
            if not src:
                continue
            done += 1
            api = src.get("api") if isinstance(src.get("api"), str) else ""
            loader = _loader(api, src.get("type"))
            if loader in ("cms", "url") and api.lower().startswith(("http://", "https://")):
                res = probe_api.probe_maccms(api, cfg, str(cfg.get("关键词", "庆余年")))
                r.probe = ProbeResult(res["state"], res["tier"], res["elapsed_ms"],
                                      res["message"], res["endpoints"])
            elif loader in ("js", "py", "jar") and api.lower().startswith(("http://", "https://")):
                res = probe_api.probe_asset(api, cfg, f"{loader} 资源")
                r.probe = ProbeResult(res["state"], res["tier"], res["elapsed_ms"],
                                      res["message"], res["endpoints"])
            else:
                r.probe = ProbeResult("跳过", "C", 0,
                                      f"{loader} 本地/相对资源，需客户端加载，契约不执行：{api[:48]}")
        return [probe_api.probe_spider(loaded[0].data.get("spider", ""), cfg)] if loaded else []

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
            if not isinstance(data, dict) or not isinstance(data.get("sites"), list):
                continue
            sites = data["sites"]
            site_keys: dict[str, list[int]] = {}
            site_names: dict[str, list[int]] = {}
            site_apis: dict[str, list[int]] = {}
            for idx, src in enumerate(sites, start=1):
                if not isinstance(src, dict):
                    continue
                key = src.get("key") if isinstance(src.get("key"), str) else ""
                name = src.get("name") if isinstance(src.get("name"), str) else key
                if "F-01" in fixes:
                    self._repair_defaults(plan, lj.path, idx, name, src, fix_cfg)
                if "F-10" in fixes:
                    self._repair_banned_fields(plan, lj.path, idx, name, src, fix_cfg)
                if "F-12" in fixes:
                    self._repair_name(plan, lj.path, idx, name, src)
                if "F-02" in fixes:
                    self._repair_numbers(plan, lj.path, idx, name, src)
                if "F-03" in fixes:
                    self._repair_switches(plan, lj.path, idx, name, src, fix_cfg)
                if "F-06" in fixes:
                    self._repair_key(plan, lj.path, idx, name, src, fix_cfg)
                if "F-07" in fixes:
                    self._repair_double_package(plan, lj.path, idx, name, src)
                if "F-08" in fixes:
                    self._repair_ext_base(plan, lj.path, idx, name, src)
                if "F-11" in fixes:
                    self._repair_ext_string(plan, lj.path, idx, name, src)
                if "S-01" in sups:
                    self._supplement_ext_v(plan, lj.path, idx, name, src, sup_cfg)
                if "S-02" in sups:
                    self._supplement_ext_base(plan, lj.path, idx, name, src)
                if "S-05" in sups:
                    self._supplement_name(plan, lj.path, idx, name, src)
                if "S-04" in sups and self.adult_mode == "打标":
                    self._converge_private(plan, lj.path, idx, name, src, sup_cfg)

                if isinstance(src.get("key"), str) and src["key"]:
                    site_keys.setdefault(src["key"], []).append(idx)
                if isinstance(src.get("name"), str) and src["name"]:
                    site_names.setdefault(src["name"], []).append(idx)
                if isinstance(src.get("api"), str) and src["api"]:
                    signature = src["api"] + "||" + json.dumps(src.get("ext"), ensure_ascii=False, sort_keys=True)
                    site_apis.setdefault(signature, []).append(idx)

                hits = self._adult_hits(src)
                if hits and self.adult_mode == "阻断":
                    plan.unhandle(lj.path, idx, name, "成人内容命中公开域：" + "、".join(hits),
                                  "内容判断类，工具不自动删除或改 key",
                                  "移入私有域（--域 私有）或私有包，公开包不收录")

            if "F-04" in fixes:
                self._repair_lives(plan, lj.path, data)
            if "F-05" in fixes:
                self._repair_flags(plan, lj.path, data)
            if "F-09" in fixes:
                self._repair_spider(plan, lj.path, data)
            if "S-03" in sups:
                self._supplement_parses_ext(plan, lj.path, data.get("parses"))
            if "S-06" in sups:
                self._supplement_lives_type(plan, lj.path, data.get("lives"))

            for key, group in site_keys.items():
                if len(group) > 1:
                    for idx in group:
                        plan.unhandle(lj.path, idx, self._name_at(sites, idx),
                                      f"key 重复：{key}", "保留哪条属于内容判断，改名会重置用户选择（TVB-NAM-005）",
                                      "人工确认保留哪条，另一条加 _a/_b 后缀（TVB-NAM-005）")
            for name, group in site_names.items():
                if len(group) > 1:
                    for idx in group:
                        plan.unhandle(lj.path, idx, name, f"name 重复：{name}",
                                      "改名属于人工判断", "主线不加后缀，备线加 ·备线（TVB-NAM-017）")
            for signature, group in site_apis.items():
                if len(group) > 1:
                    api = signature.split("||", 1)[0]
                    for idx in group:
                        plan.unhandle(lj.path, idx, self._name_at(sites, idx),
                                      f"多个站点 api 与 ext 完全相同：{api[:48]}",
                                      "同实现多 key 会被跳过预热，改哪个属于内容判断（TVB-NAM-005）",
                                      "人工确认保留主力，其余换 api/jar")
        return plan

    @staticmethod
    def _name_at(sites: list, idx: int) -> str:
        if 0 < idx <= len(sites) and isinstance(sites[idx - 1], dict):
            value = sites[idx - 1].get("name") or sites[idx - 1].get("key") or ""
            return str(value)
        return ""

    def _repair_defaults(self, plan: RepairPlan, file: str, idx: int, name: str,
                         src: dict, cfg: dict) -> None:
        for key, value in cfg.get("默认字段", {}).items():
            if key not in src:
                src[key] = value
                plan.add("F-01", "修复", file, idx, name, f"sites[{idx}].{key}", _MISSING, value,
                         "缺基础开关字段，按客户端默认值补齐（TVB-CFG-001）")

    def _repair_numbers(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        fields = list(self.cfg["数字开关字段"]) + ["type", "playerType", "timeout"]
        for field in fields:
            raw = src.get(field)
            if isinstance(raw, str) and re.fullmatch(r"-?\d+", raw.strip()):
                new = int(raw.strip())
                src[field] = new
                plan.add("F-02", "修复", file, idx, name, f"sites[{idx}].{field}", raw, new,
                         "数字字段写成字符串会被解析异常回落默认值，改为 JSON 数字（TVB-CFG-001）")

    def _repair_switches(self, plan: RepairPlan, file: str, idx: int, name: str,
                         src: dict, cfg: dict) -> None:
        for field in self.cfg["数字开关字段"]:
            raw = src.get(field)
            if isinstance(raw, bool):
                new = cfg.get("开关真值", 1) if raw else cfg.get("开关假值", 0)
                src[field] = new
                plan.add("F-03", "修复", file, idx, name, f"sites[{idx}].{field}", raw, new,
                         "布尔开关会被异常吞掉并回落 1，改为 0/1 保留作者意图（TVB-CFG-031）")

    def _repair_key(self, plan: RepairPlan, file: str, idx: int, name: str,
                    src: dict, cfg: dict) -> None:
        raw = src.get("key")
        if not isinstance(raw, str):
            return
        new = raw.strip().lower()
        for ch in cfg.get("key非法字符", []):
            new = new.replace(ch, "_")
        if new != raw:
            if self.key_re.fullmatch(new) and new not in self.cfg.get("禁用key", []):
                src["key"] = new
                plan.add("F-06", "修复", file, idx, name, f"sites[{idx}].key", raw, new,
                         "key 去空白/转小写/非法字符换下划线；改名会重置 HOME_API，需人工确认（TVB-NAM-005）",
                         need_confirm=True)
            else:
                plan.unhandle(file, idx, name, f"key 规范化后仍不合规：{new}",
                              "无法在不猜测用途的前提下改名", "按 <形态>_<用途>_<站点> 手工重命名（TVB-NAM-005）")

    def _repair_double_package(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        api = src.get("api")
        if not isinstance(api, str):
            return
        marker = "csp_com.github.catvod.spider."
        if marker in api:
            new = api.replace(marker, "csp_")
            src["api"] = new
            plan.add("F-07", "修复", file, idx, name, f"sites[{idx}].api", api, new,
                     "去掉双层包名，类名 = 第一个 csp_ 之后的全部内容（TVB-CFG-003）")

    def _repair_banned_fields(self, plan: RepairPlan, file: str, idx: int, name: str,
                              src: dict, cfg: dict) -> None:
        for field in cfg.get("删除字段", []):
            if field in src:
                old = src.pop(field)
                plan.add("F-10", "修复", file, idx, name, f"sites[{idx}].{field}", old, _MISSING,
                         f"{field} 在本仓库只写不读，删除不影响行为（TVB-CFG-031/TVB-CFG-031）")

    def _repair_name(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        raw = src.get("name")
        if not isinstance(raw, str) or not raw.strip():
            return
        new = re.sub(r"[\x00-\x1f\x7f]", "", raw)
        new = new.replace("$$$", "·").replace("|", "·").replace("#", "·").replace("$", "·")
        new = re.sub(r"·{2,}", "·", new).strip(" ·")
        if new != raw:
            src["name"] = new
            plan.add("F-12", "修复", file, idx, new, f"sites[{idx}].name", raw, new,
                     "把禁用分隔符统一成 ·，保留原文分段（TVB-NAM-016）")
        if any(ch in new for ch in self.cfg["name禁止字符"]):
            plan.unhandle(file, idx, new, f"name 仍含禁用字符：{new}",
                          "无法在不猜测语义的前提下自动改写", "人工按「站点简称·线路」重命名")

    def _repair_ext_string(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        ext = src.get("ext")
        loader = _loader(src.get("api") if isinstance(src.get("api"), str) else "", src.get("type"))
        if not isinstance(ext, str) or loader not in ("jar", "js"):
            return
        try:
            parsed = json.loads(ext)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            src["ext"] = parsed
            plan.add("F-11", "修复", file, idx, name, f"sites[{idx}].ext", ext, parsed,
                     "ext 字符串是合法 JSON 对象，按对象落盘（TVB-CFG-028）")
        else:
            plan.unhandle(file, idx, name, "ext 是字符串且不是 JSON 对象",
                          "jar/js 源要求 ext 为对象；直接改写会改变加载方式",
                          "人工确认该源是否走 drpy 类加载器，或改为对象写法（TVB-CFG-028）")

    def _repair_ext_base(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        ext = src.get("ext")
        if not isinstance(ext, dict):
            return
        base = ext.get("base")
        if isinstance(base, str):
            new = base.strip()
            while new.endswith("/"):
                new = new[:-1]
            if new != base:
                ext["base"] = new
                plan.add("F-08", "修复", file, idx, name, f"sites[{idx}].ext.base", base, new,
                         "去首尾空白与末尾斜杠，避免拼接出双斜杠")

    def _repair_lives(self, plan: RepairPlan, file: str, data: dict) -> None:
        lives = data.get("lives")
        if not isinstance(lives, list):
            return
        for i, item in enumerate(lives, start=1):
            if not isinstance(item, dict):
                continue
            raw = item.get("type")
            if isinstance(raw, int) and not isinstance(raw, bool) and raw in (0, 3):
                new = str(raw)
                item["type"] = new
                plan.add("F-04", "修复", file, -1, f"lives[{i}]", f"lives[{i}].type", raw, new,
                         "lives.type 必须写字符串 \"0\"/\"3\"，写数字会清空直播分组（TVB-CFG-012）")
            elif isinstance(raw, str) and raw.strip() in ("0", "3") and raw != raw.strip():
                item["type"] = raw.strip()
                plan.add("F-04", "修复", file, -1, f"lives[{i}]", f"lives[{i}].type", raw, raw.strip(),
                         "去掉 type 首尾空白（TVB-CFG-012）")

    def _repair_flags(self, plan: RepairPlan, file: str, data: dict) -> None:
        flags = data.get("flags")
        if not isinstance(flags, str):
            return
        parts = [p.strip() for p in flags.split(",") if p.strip()]
        data["flags"] = parts
        plan.add("F-05", "修复", file, -1, "flags", "flags", flags, parts,
                 "flags 写成字符串会静默变空列表，按逗号拆成数组（TVB-CFG-031）")

    def _repair_spider(self, plan: RepairPlan, file: str, data: dict) -> None:
        raw = data.get("spider")
        if not isinstance(raw, str):
            return
        new = raw.replace(";MD5;", ";md5;").replace(";md5:", ";md5;")
        parts = new.split(";md5;")
        if len(parts) > 1 and re.fullmatch(r"[0-9A-Fa-f]{32}", parts[1].strip()):
            digest = parts[1].strip().lower()
            if digest != parts[1].strip():
                new = ";md5;".join([parts[0], digest] + parts[2:])
        if new != raw:
            data["spider"] = new
            plan.add("F-09", "修复", file, -1, "spider", "spider", raw, new,
                     "统一 ;md5; 分隔符与 32 位小写 md5（TVB-NAM-015）")

    def _supplement_ext_v(self, plan: RepairPlan, file: str, idx: int, name: str,
                          src: dict, cfg: dict) -> None:
        ext = src.get("ext")
        loader = _loader(src.get("api") if isinstance(src.get("api"), str) else "", src.get("type"))
        if not isinstance(ext, dict) or loader not in ("jar", "js"):
            return
        if "v" not in ext:
            version = cfg.get("默认ext版本", 1)
            ext["v"] = version
            plan.add("S-01", "补充", file, idx, name, f"sites[{idx}].ext.v", _MISSING, version,
                     "ext 缺结构版本，按最小版本 1 补齐（TVB-CFG-028）")

    def _supplement_ext_base(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        ext = src.get("ext")
        if not isinstance(ext, dict) or "base" in ext:
            return
        api = src.get("api")
        if not isinstance(api, str) or not api.lower().startswith(("http://", "https://")):
            plan.unhandle(file, idx, name, "ext 缺 base 且 api 不是绝对 URL",
                          "无法确定性推断站点根地址", "人工补 ext.base（TVB-CFG-028）")
            return
        base = _origin(api)
        if base:
            ext["base"] = base
            plan.add("S-02", "补充", file, idx, name, f"sites[{idx}].ext.base", _MISSING, base,
                     "由 api 的 origin 推断站点根地址，需人工确认（TVB-CFG-028）", need_confirm=True)

    def _supplement_name(self, plan: RepairPlan, file: str, idx: int, name: str, src: dict) -> None:
        if "name" in src:
            return
        key = src.get("key")
        if isinstance(key, str) and key:
            src["name"] = key
            plan.add("S-05", "补充", file, idx, name, f"sites[{idx}].name", _MISSING, key,
                     "name 可省略，缺省时客户端取 key 作为显示名（TVB-NAM-017）")

    def _converge_private(self, plan: RepairPlan, file: str, idx: int, name: str,
                          src: dict, cfg: dict) -> None:
        if not self._adult_hits(src):
            return
        target = cfg.get("私有域收敛开关", {})
        for field, value in target.items():
            if src.get(field) != value:
                old = src.get(field, _MISSING)
                src[field] = value
                plan.add("S-04", "补充", file, idx, name, f"sites[{idx}].{field}", old, value,
                         "私有域成人条目收敛曝光：三开关置 0，仅在自身首页/分类可见（TVB-SEC-001）")

    def _supplement_parses_ext(self, plan: RepairPlan, file: str, parses: Any) -> None:
        if not isinstance(parses, list):
            return
        for i, p in enumerate(parses, start=1):
            if isinstance(p, dict) and "ext" not in p:
                p["ext"] = {}
                plan.add("S-03", "补充", file, -1, f"parses[{i}]", f"parses[{i}].ext", _MISSING, {},
                         "parses 必须显式写空对象 ext，避免写成字符串导致整份失败（TVB-CFG-031）")

    def _supplement_lives_type(self, plan: RepairPlan, file: str, lives: Any) -> None:
        if not isinstance(lives, list):
            return
        for i, item in enumerate(lives, start=1):
            if not isinstance(item, dict) or "type" in item:
                continue
            if item.get("url"):
                value = "0"
            elif item.get("api"):
                value = "3"
            else:
                continue
            item["type"] = value
            plan.add("S-06", "补充", file, -1, f"lives[{i}]", f"lives[{i}].type", _MISSING, value,
                     "由 url/api 推断直播类型并写成字符串（TVB-CFG-012）")


def load_rules(path: str) -> dict:
    return json.load(open(path, "r", encoding="utf-8-sig"))
