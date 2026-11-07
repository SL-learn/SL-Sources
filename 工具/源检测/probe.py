"""通用探活内核。

只提供 HTTP 原语 + maccms 端点探活；阅读的 URL 构造与档位判定在
adapters/reading.py，TVBox 在 adapters/tvbox.py，各自读取 rules 里的探活参数。

时限说明：Python 标准库 urllib 只能设置总超时，无法分别设置连接/读取超时，
报告中会标注「连接超时按规范、实现取总超时」。
"""

from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

UA = "Mozilla/5.0"


def request(url: str, method: str = "GET", headers: dict | None = None,
            body: bytes | None = None, timeout: float = 10.0) -> dict:
    """单次 HTTP 请求，不抛异常，返回统一结构。"""
    started = time.perf_counter()
    req_headers = {"User-Agent": UA}
    if headers:
        req_headers.update({str(k): str(v) for k, v in headers.items()})
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    status = 0
    text = ""
    content_type = ""
    error = ""
    final_url = url
    raw = b""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "") or ""
            raw = resp.read()
            text = raw.decode("utf-8", "ignore")
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            text = e.read().decode("utf-8", "ignore")
        except Exception:
            text = ""
        error = f"HTTP-{e.code}"
    except urllib.error.URLError as e:
        error = f"网络错误：{e.reason}"
    except ssl.SSLError as e:
        error = f"证书/SSL错误：{e}"
    except Exception as e:      # 超时、DNS、连接重置等
        error = f"{type(e).__name__}：{e}"
    elapsed = int((time.perf_counter() - started) * 1000)
    return {
        "url": url, "final_url": final_url, "status": status, "elapsed_ms": elapsed,
        "content_type": content_type, "text": text, "bytes": len(raw),
        "md5": hashlib.md5(raw).hexdigest() if raw else "",
        "error": error,
    }


def request_with_retry(url: str, method: str = "GET", headers: dict | None = None,
                       body: bytes | None = None, timeout: float = 10.0,
                       retries: int = 0, interval: float = 1.0) -> dict:
    """按规范重试：只对超时/网络错误/5xx 重试，4xx 不重试。"""
    result = request(url, method, headers, body, timeout)
    attempt = 0
    while attempt < retries:
        retryable = (not result["status"]) or result["status"] >= 500
        if not retryable:
            break
        attempt += 1
        if interval > 0:
            time.sleep(interval)
        result = request(url, method, headers, body, timeout)
    return result


def median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) // 2


def _endpoint(name: str, url: str, res: dict, verdict: str, note: str = "") -> dict:
    return {"名称": name, "URL": url, "状态码": res.get("status", 0),
            "耗时毫秒": res.get("elapsed_ms", 0), "结论": verdict, "说明": note or res.get("error", "")}


def _api_url(api: str, query: str) -> str:
    sep = "&" if "?" in api else "?"
    return f"{api}{sep}{query}"


def probe_maccms(api: str, cfg: dict, keyword: str = "庆余年") -> dict:
    """maccms（type=0）三端点探活。

    端点与判据来自《小猫影视 自建源统一规格规范》CAT-PRB-002/CAT-PRB-003：
    ac=list、ac=detail&ids=首条、ac=detail&wd=关键词；
    每端点最多 2 次请求（共 ≤6），4xx 不重试。
    返回 dict：state/tier/elapsed_ms/message/endpoints。
    """
    timeout = float(cfg.get("总超时秒", cfg.get("超时秒", 10)))
    retries = int(cfg.get("重试", 1))
    headers = {"User-Agent": cfg.get("请求头UA", UA)}

    ep1 = _api_url(api, "ac=list")
    r1 = request_with_retry(ep1, timeout=timeout, retries=retries, interval=float(cfg.get("重试间隔秒", 1)))
    data = None
    note = ""
    try:
        data = json.loads(r1["text"])
    except Exception:
        note = "返回体不是 JSON" if r1["text"] else "返回体为空"
    class_count = len(data.get("class", []) or []) if isinstance(data, dict) else 0
    pagecount = int(data.get("pagecount", 0) or 0) if isinstance(data, dict) else 0
    total = int(data.get("total", 0) or 0) if isinstance(data, dict) else 0
    vod_id = ""
    if isinstance(data, dict):
        for item in (data.get("list") or []):
            if isinstance(item, dict) and item.get("vod_id"):
                vod_id = str(item["vod_id"])
                break
    ok1 = bool(r1["status"] == 200 and isinstance(data, dict))
    endpoints = [_endpoint("ac=list", ep1, r1,
                           "通过" if ok1 else "失败",
                           f"分类={class_count} pagecount={pagecount} total={total} {note}".strip())]

    ok2 = False
    if vod_id:
        ep2 = _api_url(api, f"ac=detail&ids={urllib.parse.quote(vod_id)}")
        r2 = request_with_retry(ep2, timeout=timeout, retries=retries, interval=float(cfg.get("重试间隔秒", 1)))
        try:
            d2 = json.loads(r2["text"])
            ok2 = bool(r2["status"] == 200 and isinstance(d2, dict) and (d2.get("list") or []))
        except Exception:
            ok2 = False
        endpoints.append(_endpoint("ac=detail&ids", ep2, r2, "通过" if ok2 else "失败"))
    else:
        endpoints.append({"名称": "ac=detail&ids", "URL": "", "状态码": 0, "耗时毫秒": 0,
                          "结论": "跳过", "说明": "端点1 未返回可用 vod_id"})

    ep3 = _api_url(api, f"ac=detail&wd={urllib.parse.quote(keyword)}&pg=1")
    r3 = request_with_retry(ep3, timeout=timeout, retries=retries, interval=float(cfg.get("重试间隔秒", 1)))
    try:
        d3 = json.loads(r3["text"])
        ok3 = bool(r3["status"] == 200 and isinstance(d3, dict) and (d3.get("list") or []))
    except Exception:
        ok3 = False
    endpoints.append(_endpoint("ac=detail&wd", ep3, r3, "通过" if ok3 else "失败"))

    passed = sum(1 for e in endpoints if e["结论"] == "通过")
    elapsed = sum(e["耗时毫秒"] for e in endpoints)
    median_ms = median([e["耗时毫秒"] for e in endpoints if e["耗时毫秒"]])
    blocked = any(e["状态码"] in (403, 429) or "证书" in e["说明"] or
                  ("不是 JSON" in e["说明"]) for e in endpoints)

    if pagecount == 0 and isinstance(data, dict) and ok1:
        tier, state, msg = "D", "失败", "端点1 可解析但 pagecount=0，判空库/不可用"
    elif passed == 3 and class_count >= 5 and pagecount >= 100 and total >= 1000 and median_ms <= 3000:
        tier, state, msg = "A", "通过", f"三端点通过，分类 {class_count}、pagecount {pagecount}、total {total}，中位 {median_ms}ms"
    elif passed >= 2:
        tier, state, msg = "B", "通过", f"{passed}/3 端点通过，中位 {median_ms}ms（间歇可用）"
    elif blocked:
        tier, state, msg = "C", "跳过", "403/429/证书/非 JSON，无法判定"
    elif passed <= 1:
        tier, state, msg = "D", "失败", f"仅 {passed}/3 端点通过"
    else:
        tier, state, msg = "C", "跳过", "证据不足，待复探"
    if blocked and tier != "C":
        tier, state, msg = "C", "跳过", "存在 403/429/证书/非 JSON 响应，按无法判定处理"
    return {"state": state, "tier": tier, "elapsed_ms": elapsed, "message": msg,
            "endpoints": endpoints}


def probe_asset(url: str, cfg: dict, label: str) -> dict:
    """脚本/资源可达性探活：只判能否下载，不执行契约。"""
    timeout = float(cfg.get("总超时秒", 10))
    res = request_with_retry(url, timeout=timeout, retries=int(cfg.get("重试", 1)))
    ok = res["status"] == 200 and res["bytes"] > 0
    note = f"{label}可下载（{res['bytes']} 字节），契约未执行" if ok else res["error"] or f"HTTP-{res['status']}"
    return {"state": "通过" if ok else "失败", "tier": "C" if ok else "D",
            "elapsed_ms": res["elapsed_ms"], "message": note,
            "endpoints": [_endpoint(label, url, res, "通过" if ok else "失败")]}


def probe_spider(spider: str, cfg: dict) -> dict:
    """顶层 spider 探活：下载并核对 md5（若配置里带 ;md5;）。"""
    raw = str(spider or "").strip()
    if not raw:
        return {"对象": "spider", "状态": "跳过", "说明": "未配置 spider"}
    parts = raw.split(";md5;")
    url = parts[0].strip()
    expected = parts[1].strip().lower() if len(parts) > 1 else ""
    if not url.lower().startswith(("http://", "https://")):
        return {"对象": "spider", "状态": "跳过",
                "说明": f"本地/相对路径 {url}，需客户端加载，工具不下载"}
    res = request_with_retry(url, timeout=float(cfg.get("总超时秒", 10)),
                              retries=int(cfg.get("重试", 1)))
    if res["status"] != 200:
        return {"对象": "spider", "状态": "失败",
                "说明": f"HTTP-{res['status']} {res['error']}，耗时 {res['elapsed_ms']}ms"}
    digest = res.get("md5", "")
    if expected:
        ok = digest == expected
        return {"对象": "spider", "状态": "通过" if ok else "失败",
                "说明": f"下载 {res['bytes']} 字节，md5 {digest}，配置 {expected}，"
                        f"{'一致' if ok else '不一致'}"}
    return {"对象": "spider", "状态": "通过",
            "说明": f"下载 {res['bytes']} 字节，耗时 {res['elapsed_ms']}ms，配置未带 md5"}
