# -*- coding: utf-8 -*-
"""TVBox 站点逐条体检。

分层口径：
  A 实测层：`api` 为 `./js/cms.js`（JS 包装的 MacCMS 源），脚本从 cms.js 的 HOSTS 取上游地址，
    按 MacCMS 接口实测分类、首页、搜索、详情、播放与三次响应均值。
  B 静态层：jar/py/自有 js 爬虫，上游地址无法静态取得，HTTP 不可探测；只核验本地引用与 jar md5。

判定纪律：
  网络不可达、超时、被网关拦截一律记「需复测」，不得写成「剔除」。
  「剔除」只在拿到有效上游响应且确认无内容时使用。

输出（不覆盖既有探活报告）：
  记录/<YYYY-MM-DD>/tvbox/源体检表.csv
  记录/<YYYY-MM-DD>/tvbox/源体检表.md
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import ssl
import time
import urllib.request
from collections import Counter
from urllib.parse import quote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APP_DIR = os.path.join(ROOT, "apps", "tvbox")

UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

ADULT = re.compile(
    r"理论|伦理|成人|福利|情色|色情|三级|写真|里番|无码|有码|自拍|偷拍|约炮|激情|"
    r"男同|女同|同志|啪啪|裸|艳照|淫|擦边|两性"
)
NONVIDEO = re.compile(r"新闻|资讯|动态|爆料|公告|专题|评论|八卦")

CONTENT = [
    ("📚听书", re.compile(r"听书|评书|有声|相声|小品|戏曲|京剧|越剧|黄梅|梆子|曲艺|故事|广播|电台|音乐|DJ|歌曲")),
    ("🎠少儿", re.compile(r"少儿|儿童|幼儿|幼教|早教|宝宝|亲子|儿歌|童话|启蒙|识字|拼音|口才|思维|动画片|小朋友")),
    ("⚽体育", re.compile(r"看球|体育|足球|篮球|网球|斯诺克|赛事|NBA|CBA")),
    ("🩺养生/生活", re.compile(r"养生|健康|急救|中医|知识|科普|生活|美食|菜谱|记录片|纪录片")),
    ("🎬短剧", re.compile(r"短剧")),
    ("🎌动漫", re.compile(r"动漫|番剧|二次元|漫剧|漫画|ACG")),
    ("🎤综艺", re.compile(r"综艺|演唱会|脱口秀|晚会")),
    ("📺剧集", re.compile(r"剧集|电视剧|连续剧|韩剧|美剧|日剧|港剧|台剧|泰剧")),
    ("🎞电影", re.compile(r"电影|片库|影库|4K|蓝光|高清电影")),
    ("🎬综合影视", re.compile(r"影视|视频|影院|资源|秒播|弹幕|综合|影|剧|看")),
]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def lines_of_app() -> list[tuple[str, str]]:
    meta = json.load(open(os.path.join(APP_DIR, "version.json"), encoding="utf-8"))
    return [(ln["code"], ln["dir"]) for ln in meta["lines"]]


def hosts_map() -> tuple[dict[str, str], str]:
    """从含 cms.js 的线路目录读取 HOSTS 表。"""
    for _, d in lines_of_app():
        p = os.path.join(APP_DIR, d, "js", "cms.js")
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8", errors="ignore").read()
        block = txt.split("const HOSTS = {", 1)[-1].split("};", 1)[0]
        hosts = {}
        for m in re.finditer(r"['\"]([A-Za-z0-9_]+)['\"]\s*:\s*['\"]([^'\"]+)['\"]", block):
            hosts[m.group(1)] = m.group(2)
        return hosts, d
    return {}, ""


def http_get(url: str, timeout: int, ua: str) -> tuple[int | None, bytes, int, str]:
    req = urllib.request.Request(quote(url, safe=":/?&=#%"), headers={"User-Agent": ua})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read(), int((time.time() - t0) * 1000), ""
    except Exception as e:  # noqa: BLE001 网络异常统一归为不可达
        return None, b"", int((time.time() - t0) * 1000), str(e)


def jload(body: bytes):
    for enc in ("utf-8", "gbk"):
        try:
            return json.loads(body.decode(enc, "ignore"))
        except Exception:
            pass
    return None


def classify(name: str, classes: list[str] | None = None) -> tuple[str, str]:
    if classes:
        hit: dict[str, int] = {}
        for c in classes:
            for sym, rx in CONTENT:
                if rx.search(c):
                    hit[sym] = hit.get(sym, 0) + 1
        if hit:
            return max(hit.items(), key=lambda kv: kv[1])[0], "实测分类"
        return "🎬综合影视", "实测分类(全为通用分类)"
    for sym, rx in CONTENT:
        if rx.search(name):
            return sym, "名称静态判定"
    return "🎬综合影视", "名称静态判定(无关键词)"


def static_check(site: dict, line_dir: str) -> tuple[list[str], list[str]]:
    issues, ev = [], []
    for label in ("api", "ext"):
        ref = str(site.get(label) or "")
        if ref.startswith("./"):
            p = os.path.join(APP_DIR, line_dir, ref[2:])
            if os.path.exists(p):
                ev.append(f"{label}={os.path.getsize(p) // 1024}KB")
            else:
                issues.append(f"{label} 文件缺失 {ref}")
    jar = str(site.get("jar") or "")
    if jar.startswith("../_common/jar/"):
        p = os.path.join(APP_DIR, "_common", "jar", jar.split("/")[-1].split(";md5;")[0])
        if not os.path.exists(p):
            issues.append("jar 文件缺失")
        else:
            want = jar.split(";md5;")[-1].strip() if ";md5;" in jar else ""
            got = hashlib.md5(open(p, "rb").read()).hexdigest()
            if want and want != got:
                issues.append("jar md5 不符")
            ev.append("jar ok")
    elif jar.startswith("./"):
        p = os.path.join(APP_DIR, line_dir, jar.split(";md5;")[0][2:])
        if not os.path.exists(p):
            issues.append("jar 文件缺失")
        else:
            ev.append("jar ok")
    return issues, ev


def probe_cms(up: str, timeout: int) -> dict:
    r = {"cls_n": "", "cls_all": [], "cls_kept": [], "cls_cut": [],
         "home": "", "search": "", "detail": "", "play": "", "m3u8": "",
         "ms": "", "state": "", "reason": "", "ua": ""}

    times, last_err = [], ""
    for _ in range(3):
        st, body, t, err = http_get(up + "?ac=list", timeout, "okhttp/3.15")
        times.append(t)
        if st != 200 and err:
            last_err = err
    r["ms"] = int(sum(times) / len(times))

    st, body, _, err = http_get(up + "?ac=list", timeout, "okhttp/3.15")
    if st != 200:
        # okhttp UA 失败时换浏览器 UA 复核，区分「UA/网关差异」与「真不可达」
        st2, body2, _, err2 = http_get(up + "?ac=list", timeout, UA_BROWSER)
        if st2 == 200:
            r["state"] = "UA_GATE"
            r["reason"] = f"okhttp UA 被拒（{err or 'HTTP ' + str(st)}），浏览器 UA 可通"
            r["ua"] = "browser"
            st, body = st2, body2
        else:
            r["state"] = "UNREACHABLE"
            r["reason"] = f"不可达或超时：{err or err2 or 'HTTP ' + str(st)}"
            return r
    r["ua"] = "okhttp"

    j = jload(body)
    if not isinstance(j, dict):
        r["state"] = "BAD_JSON"
        r["reason"] = "ac=list 返回非 JSON（疑似网关/反爬页）"
        return r
    cl = j.get("class")
    if not isinstance(cl, list):
        cl = []
    names = [str(c.get("type_name", "")).strip() for c in cl if isinstance(c, dict)]
    r["cls_all"] = [n for n in names if n]
    r["cls_n"] = len(r["cls_all"])

    parent_ids = set()
    for c in cl:
        pid = c.get("type_pid", 0)
        if pid and str(pid) != "0":
            parent_ids.add(str(pid))
    kept, cut = [], []
    for c in cl:
        if not isinstance(c, dict):
            continue
        nm = str(c.get("type_name", "")).strip()
        if not nm or c.get("type_id") is None:
            continue
        if ADULT.search(nm) or NONVIDEO.search(nm):
            cut.append(nm)
        elif str(c.get("type_id")) in parent_ids:
            cut.append(nm)
        else:
            kept.append(nm)
    r["cls_kept"], r["cls_cut"] = kept, cut

    st, body, _, err = http_get(up + "?ac=detail&pg=1", timeout, "okhttp/3.15")
    j = jload(body) if st == 200 else None
    r["home"] = len((j or {}).get("list") or []) if isinstance(j, dict) else -1

    tids = [c for c in cl if isinstance(c, dict)
            and str(c.get("type_name", "")).strip() in kept]
    if tids:
        tid = tids[0].get("type_id")
        st, body, _, _ = http_get(f"{up}?ac=detail&t={tid}&pg=1", timeout, "okhttp/3.15")
        j = jload(body) if st == 200 else None
        lst = (j or {}).get("list") or [] if isinstance(j, dict) else []
        if lst:
            vid = lst[0].get("vod_id")
            st, body, _, _ = http_get(f"{up}?ac=detail&ids={vid}", timeout, "okhttp/3.15")
            j = jload(body) if st == 200 else None
            d0 = ((j or {}).get("list") or [{}])[0] if isinstance(j, dict) else {}
            pu = str(d0.get("vod_play_url", ""))
            r["detail"] = 1 if d0 else 0
            r["play"] = 1 if pu else 0
            r["m3u8"] = 1 if (".m3u8" in pu or ".sm3u8" in pu) else 0

    st, body, _, _ = http_get(up + "?ac=detail&wd=" + quote("测试"), timeout, "okhttp/3.15")
    j = jload(body) if st == 200 else None
    r["search"] = len((j or {}).get("list") or []) if isinstance(j, dict) else -1

    if r["cls_n"] == 0:
        r["state"] = "NO_CLASS"
        r["reason"] = "ac=list 返回 class 为空"
    elif not kept and cut:
        r["state"] = "WEAK_CLASS"
        r["reason"] = "分类全部为成人/非影视/父分类：" + "/".join(cut[:6])
    elif r["cls_n"] <= 2:
        r["state"] = "WEAK_CLASS"
        r["reason"] = "仅 " + "/".join(r["cls_all"][:3]) + "，无内容细分"
    else:
        r["state"] = "OK"
    return r


def verdict_of(r: dict) -> tuple[str, str]:
    st = r["state"]
    if st == "UNREACHABLE":
        return "需复测", r["reason"]
    if st == "BAD_JSON":
        return "需复测", r["reason"]
    if st == "UA_GATE":
        return "需复测", r["reason"] + "；接入侧需带对应 UA/头"
    if st == "NO_CLASS":
        if r["home"] == -1 and r["search"] == -1:
            return "需复测", "无分类且首页/搜索请求失败"
        if not r["home"] and not r["search"]:
            return "剔除", "无分类且首页/搜索均空"
        return "需修复", "无分类，但首页/搜索有数据，分类解析需复核"
    if not r["home"] and not r["search"]:
        return "剔除", "首页与搜索均空"
    if r["ms"] >= 4000 or st == "WEAK_CLASS" or not r["search"]:
        return "降为备用", f"耗时 {r['ms']}ms / 分类 {r['cls_n']} / 搜索 {r['search']}"
    if not r["play"] or not r["detail"]:
        return "需修复", "详情或播放地址取不到"
    return "保留", "四环通过"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--超时", type=int, default=8)
    ap.add_argument("--日期", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--输出", default="")
    ap.add_argument("--复用", action="store_true", help="复用已有 CSV，只重算汇总，不重新联网")
    ap.add_argument("--重算归类", action="store_true", help="配合 --复用：静态层按现名重算内容归类")
    ns = ap.parse_args()
    out_dir = ns.输出 or os.path.join(ROOT, "记录", ns.日期, "tvbox")
    out_csv = os.path.join(out_dir, "源体检表.csv")

    rows = []
    if ns.复用 and os.path.exists(out_csv):
        with open(out_csv, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            if row["实测层级"] == "静态":
                row["无分类类型"] = "不可判定（未实测）"
                if ns.重算归类:
                    row["内容归类"], row["归类依据"] = classify(row["现名"])
            elif row["结论"] == "需复测":
                row["无分类类型"] = "不可判定（需复测）"
            elif not row["无分类类型"]:
                row["无分类类型"] = "无（分类正常）"
        print(f"复用 {out_csv}，共 {len(rows)} 条")
        return write_reports(rows, out_dir)

    hosts, host_line = hosts_map()
    if not hosts:
        print("未找到 cms.js 的 HOSTS 表，实测层将为空。")
    rows = []
    for code, line_dir in lines_of_app():
        cfg = json.load(open(os.path.join(APP_DIR, line_dir, "api.json"), encoding="utf-8"))
        for s in cfg["sites"]:
            api = str(s.get("api", ""))
            if api == "./js/cms.js":
                up = hosts.get(s["key"])
            elif api.startswith(("http://", "https://")) and s.get("type") in (0, 1):
                up = api
            else:
                up = None
            row = {
                "线路": code, "key": s["key"], "现名": s["name"], "type": s.get("type"),
                "api": api, "上游": up or "",
                "实测层级": "实测" if up else "静态",
                "内容归类": "", "归类依据": "", "分类数": "", "分类明细": "",
                "剔除分类": "", "首页点播数": "", "搜索条数": "", "详情可解析": "",
                "播放可取": "", "m3u8": "", "三次均值ms": "", "无分类类型": "",
                "结论": "", "备注": "",
            }
            if up:
                r = probe_cms(up, ns.超时)
                sym, src = classify(s["name"], r["cls_kept"] or r["cls_all"])
                row.update({
                    "内容归类": sym, "归类依据": src,
                    "分类数": r["cls_n"] if r["state"] not in ("UNREACHABLE", "BAD_JSON") else "—",
                    "分类明细": "/".join(r["cls_all"][:10]),
                    "剔除分类": "/".join(r["cls_cut"][:8]),
                    "首页点播数": r["home"] if r["home"] != -1 else "—",
                    "搜索条数": r["search"] if r["search"] != -1 else "—",
                    "详情可解析": ("是" if r["detail"] else "否") if r["detail"] != "" else "—",
                    "播放可取": ("是" if r["play"] else "否") if r["play"] != "" else "—",
                    "m3u8": ("是" if r["m3u8"] else "否") if r["m3u8"] != "" else "—",
                    "三次均值ms": r["ms"],
                })
                v, note = verdict_of(r)
                row["结论"], row["备注"] = v, note
                row["无分类类型"] = {
                    "NO_CLASS": "上游无分类",
                    "WEAK_CLASS": "弱分类",
                    "BAD_JSON": "我方解析失败",
                }.get(r["state"], "不可判定（需复测）"
                      if r["state"] == "UNREACHABLE" else "无（分类正常）")
            else:
                issues, ev = static_check(s, line_dir)
                sym, src = classify(s["name"])
                row.update({
                    "内容归类": sym, "归类依据": src, "分类数": "未实测",
                    "首页点播数": "未实测", "搜索条数": "未实测",
                    "详情可解析": "未实测", "播放可取": "未实测", "m3u8": "未实测",
                    "三次均值ms": "未实测",
                    "结论": "需修复" if issues else "未实测",
                    "备注": "；".join(issues) if issues else "爬虫类（jar/py/js），HTTP 不可探测，需实机确认",
                    "分类明细": ",".join(ev), "无分类类型": "不可判定（未实测）",
                })
            rows.append(row)
            print(f"{code}\t{s['key']}\t{row['结论']}\t{row['内容归类']}\tcls={row['分类数']}\tms={row['三次均值ms']}", flush=True)

    return write_reports(rows, out_dir)


def write_reports(rows: list[dict], out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    out_csv = os.path.join(out_dir, "源体检表.csv")
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    measured = [x for x in rows if x["实测层级"] == "实测"]
    static = [x for x in rows if x["实测层级"] == "静态"]
    vc = Counter(x["结论"] for x in rows)
    nc = Counter(x["无分类类型"] for x in rows)
    cc = Counter(x["内容归类"] for x in rows)

    L = ["# 源体检表（TVBox）", "",
         f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
         f"- 总数：{len(rows)} 条；实测层（CMS 可探测）：{len(measured)} 条；静态层（爬虫不可探测）：{len(static)} 条",
         "- 明细：同目录 `源体检表.csv`",
         "- 口径：网络不可达/超时/被网关拦截记「需复测」，不判「剔除」。", "",
         "## 一、结论分布", "", "| 结论 | 条数 |", "|---|---|"]
    for k in ["保留", "降为备用", "需修复", "需复测", "剔除", "未实测"]:
        if vc.get(k):
            L.append(f"| {k} | {vc[k]} |")
    L += ["", "## 二、「无分类」三类定性", "", "| 类型 | 条数 | 说明 |", "|---|---|---|"]
    desc = {
        "上游无分类": "上游 ac=list 返回 class 为空",
        "我方解析失败": "上游返回非 JSON 或结构不符，分类解析不到",
        "弱分类": "有分类但仅 1-2 个笼统分类，或无有效细分",
        "无（分类正常）": "实测拿到有效分类，无下列三类问题",
        "不可判定（需复测）": "网络不可达或返回非 JSON，分类拿不到",
        "不可判定（未实测）": "爬虫类站点，HTTP 不可探测",
    }
    for k, v in nc.most_common():
        L.append(f"| {k} | {v} | {desc.get(k, '')} |")
    L += ["", "## 三、内容归类分布（静态判定仅供排序，非质量结论）", "", "| 归类 | 条数 |", "|---|---|"]
    for k, v in cc.most_common():
        L.append(f"| {k} | {v} |")
    L += ["", "## 四、实测层逐条结果", "",
          "| 线路 | key | 现名 | 内容归类 | 分类数 | 首页 | 搜索 | 详情 | 播放 | m3u8 | 均值ms | 结论 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in measured:
        L.append(f"| {x['线路']} | {x['key']} | {x['现名']} | {x['内容归类']} | {x['分类数']} | "
                 f"{x['首页点播数']} | {x['搜索条数']} | {x['详情可解析']} | {x['播放可取']} | "
                 f"{x['m3u8']} | {x['三次均值ms']} | {x['结论']} |")
    L += ["", "## 五、需修复 / 需复测 / 剔除清单", ""]
    bad = [x for x in rows if x["结论"] in ("需修复", "需复测", "剔除")]
    if bad:
        L += ["| 线路 | key | 现名 | 结论 | 原因 |", "|---|---|---|---|---|"]
        for x in bad:
            L.append(f"| {x['线路']} | {x['key']} | {x['现名']} | {x['结论']} | {x['备注']} |")
    else:
        L.append("无。")
    L += ["", "## 六、口径说明", "",
          "- 实测层：`api` 为 `./js/cms.js` 的站点取 cms.js 的 `HOSTS`，`api` 为 http(s) 且 `type` 为 0/1 的站点直接用其地址；均按 MacCMS 接口实测。",
          "- 静态层：jar/py/自有 js 爬虫，上游地址不可静态取得，HTTP 不可探测；只核验本地引用与 md5，结论记「未实测」。",
          "- 判定优先级：不可达/超时/反爬 → 需复测；无分类且首页与搜索均空 → 剔除；分类可用但详情或播放取不到 → 需修复。",
          "- 播放判定：详情 `vod_play_url` 含 `.m3u8`/`.sm3u8` 记通过。"]
    out_md = os.path.join(out_dir, "源体检表.md")
    open(out_md, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"WROTE {out_csv}")
    print(f"WROTE {out_md}")
    print("结论分布", dict(vc))
    print("无分类", dict(nc))
    print("内容归类", dict(cc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
