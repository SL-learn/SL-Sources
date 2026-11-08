"""TVBox 源生成：一条命令重建全部发布物。

用法（仓库根执行）：
    python 工具/源生成/生成.py                    # 生成并自检（默认 github 平台）
    python 工具/源生成/生成.py --check            # 只自检，不写文件
    python 工具/源生成/生成.py --platform gitee [--owner <Gitee 个性地址>]

输入：apps/tvbox/{std,kids,elders}/api.json（唯一事实来源，手改这里）
     规则/平台地址.json（raw 基址，禁止在脚本里写死某一平台）
输出：apps/tvbox/api_index.json、api_index_local.json、api_index_rel.json、api_all.json
      （gitee 版 api_index.json 的三条线路统一指向 api_all.json，见 规范/仓库通用规范.md SYS-DIST-009）
幂等：内容不变则不重写；先全部在内存算完再统一落盘，任何异常不产生半成品。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from urllib.parse import urlparse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_DIR = os.path.join(REPO, "apps", "tvbox")
PLATFORM_FILE = os.path.join(REPO, "规则", "平台地址.json")
LOCAL_ROOT = "tvbox"
LINES = [("std", "std", "综合"), ("kid", "kids", "少儿"), ("eld", "elders", "长辈")]


def raw_base(platform: str | None = None, owner: str | None = None) -> str:
    """按平台取 raw 基址（不含 /apps/tvbox/）。基址只从 规则/平台地址.json 读。"""
    platform = platform or os.environ.get("RAW_PLATFORM") or "github"
    with open(PLATFORM_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    try:
        p = cfg["平台"][platform]
    except KeyError:
        raise SystemExit(f"未知平台：{platform}（可选 {sorted(cfg['平台'])}）")
    owner = owner or p.get("owner") or os.environ.get("GITEE_OWNER", "")
    if not owner:
        raise SystemExit(f"{p['名称']} 的 owner 未配置：渲染/推送前先设环境变量 GITEE_OWNER 或用 --owner 传入")
    return p["raw"].replace("{owner}", owner)


def abs_ref(ref: str, line_dir: str, base: str) -> str:
    if not isinstance(ref, str):
        return ref
    path, sep, tail = ref.partition(";md5;")
    if path.startswith("../"):
        full = base + "/apps/tvbox/" + path[3:]
    elif path.startswith("./"):
        full = base + "/apps/tvbox/" + line_dir + "/" + path[2:]
    else:
        return ref
    return full + sep + tail


def build(base: str, platform: str = "github") -> dict:
    merged, online, local, rel = [], [], [], []
    spider = ""
    stamp = ""
    for code, line_dir, label in LINES:
        cfg_path = os.path.join(APP_DIR, line_dir, "api.json")
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        for site in cfg.get("sites", []):
            s = dict(site)
            for k in ("api", "jar", "ext"):
                if k in s:
                    s[k] = abs_ref(s[k], line_dir, base)
            merged.append(s)
        if code == "std":
            spider = abs_ref(cfg.get("spider", ""), line_dir, base)
            stamp = str(cfg.get("updateTime", "") or "")
        # Gitee 对 apps/tvbox/std/api.json 返回 451（内容审核），其索引三条线路统一指向全量单文件；
        # GitHub 版保持三线路各自地址不变（见 规范/仓库通用规范.md SYS-DIST-009）。
        if platform == "gitee":
            online.append({"name": label, "url": base + "/apps/tvbox/api_all.json"})
        else:
            online.append({"name": label, "url": base + "/apps/tvbox/" + line_dir + "/api.json"})
        local.append({"name": label, "url": f"clan://localhost/{LOCAL_ROOT}/{line_dir}/api.json"})
        # 可搬迁版：线路地址写 ./ 相对路径，由客户端按索引自身 URL 解析（ApiConfig.fixContentPath）。
        # 整包上传到自选云盘后，入口不必指回 GitHub/Gitee；线路目录已是 ASCII 短名，不涉及百分号编码。
        rel.append({"name": label, "url": f"./{line_dir}/api.json"})
    if not stamp:
        from datetime import datetime
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "api_all.json": {"updateTime": stamp, "spider": spider, "wallpaper": "",
                         "sites": merged, "lives": [], "parses": [], "flags": []},
        "api_index.json": {"updateTime": stamp, "urls": online},
        "api_index_local.json": {"updateTime": stamp, "urls": local},
        "api_index_rel.json": {"updateTime": stamp, "urls": rel},
    }


def local_refs(line_dir: str, site: dict) -> list[str]:
    out = []
    for k in ("api", "ext", "jar"):
        v = str(site.get(k, "") or "")
        if v.startswith("./"):
            out.append(os.path.join(APP_DIR, line_dir, v.split(";md5;")[0][2:]))
        elif v.startswith("../"):
            out.append(os.path.normpath(os.path.join(APP_DIR, line_dir, v.split(";md5;")[0])))
    return out


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def self_check() -> list[str]:
    problems = []
    keys = []
    for code, line_dir, label in LINES:
        cfg = json.load(open(os.path.join(APP_DIR, line_dir, "api.json"), encoding="utf-8"))
        if not isinstance(cfg.get("sites"), list) or not cfg["sites"]:
            problems.append(f"{line_dir}: sites 为空")
        for site in cfg.get("sites", []):
            keys.append(site["key"])
            for p in local_refs(line_dir, site):
                if not os.path.exists(p):
                    problems.append(f"{line_dir}/{site['key']}: 引用缺失 {p}")
            jar = str(site.get("jar", "") or "")
            if ";md5;" in jar and jar.startswith("../"):
                p = os.path.join(APP_DIR, jar.split(";md5;")[0])
                if os.path.exists(p) and md5_of(p) != jar.split(";md5;")[-1].strip():
                    problems.append(f"{line_dir}/{site['key']}: jar md5 不符")
        sp = str(cfg.get("spider", ""))
        if sp.startswith("./"):
            p = os.path.join(APP_DIR, line_dir, sp.split(";md5;")[0][2:])
            if not os.path.exists(p):
                problems.append(f"{line_dir}: spider 缺失 {p}")
            elif ";md5;" in sp and md5_of(p) != sp.split(";md5;")[-1].strip():
                problems.append(f"{line_dir}: spider md5 不符")
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        problems.append(f"key 重复：{sorted(dup)}")
    return problems


def git_head_keys() -> dict:
    """从 git HEAD 取上一版 key 集合；非 git 环境返回空。"""
    import subprocess
    out = {}
    for code, line_dir, _label in LINES:
        try:
            raw = subprocess.check_output(
                ["git", "-C", REPO, "show", f"HEAD:apps/tvbox/{line_dir}/api.json"],
                stderr=subprocess.DEVNULL)
            out[line_dir] = [s["key"] for s in json.loads(raw.decode("utf-8")).get("sites", [])]
        except Exception:
            out[line_dir] = []
    return out


def write_if_changed(name: str, data: dict) -> bool:
    path = os.path.join(APP_DIR, name)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if os.path.exists(path) and open(path, encoding="utf-8").read() == text:
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只自检，不写文件")
    ap.add_argument("--platform", default=None, help="github | gitee（默认读 RAW_PLATFORM 或 github）")
    ap.add_argument("--owner", default=None, help="覆盖 规则/平台地址.json 里的 owner")
    ns = ap.parse_args()

    platform = ns.platform or os.environ.get("RAW_PLATFORM") or "github"
    base = raw_base(platform, ns.owner)
    problems = self_check()
    out = build(base, platform)
    counts = {line: len(json.load(open(os.path.join(APP_DIR, line, "api.json"), encoding="utf-8"))["sites"])
              for _c, line, _l in LINES}
    print("raw 基址:", base)
    print("站点数:", counts, "合计:", sum(counts.values()))
    print("合并后 key 唯一:", len({s['key'] for s in out['api_all.json']['sites']}) == sum(counts.values()))

    before = git_head_keys()
    if any(before.values()):
        for _c, line, _l in LINES:
            cur = [s["key"] for s in json.load(open(os.path.join(APP_DIR, line, "api.json"), encoding="utf-8"))["sites"]]
            same = sorted(before[line]) == sorted(cur)
            print(f"key 集合对比 {line}: 改前 {len(before[line])} 改后 {len(cur)} {'一致' if same else '不一致'}")

    if problems:
        print("自检问题:", len(problems))
        for p in problems[:20]:
            print(" -", p)
        return 1
    print("自检通过：引用存在、md5 一致、key 唯一")
    if ns.check:
        print("--check：未写文件")
        return 0
    changed = [n for n in ("api_index.json", "api_index_local.json", "api_index_rel.json", "api_all.json")
               if write_if_changed(n, out[n])]
    print("已更新:", changed or "无变化")
    return 0


if __name__ == "__main__":
    sys.exit(main())
