"""TVBox 源生成：一条命令重建全部发布物。

用法（仓库根执行）：
    python 工具/源生成/生成.py            # 生成并自检
    python 工具/源生成/生成.py --check    # 只自检，不写文件

输入：apps/tvbox/{std,kids,elders}/api.json（唯一事实来源，手改这里）
输出：apps/tvbox/api_index.json、api_index_local.json、api_all.json
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
RAW = "https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/"
LOCAL_ROOT = "tvbox"
LINES = [("std", "std", "综合"), ("kid", "kids", "少儿"), ("eld", "elders", "长辈")]


def abs_ref(ref: str, line_dir: str) -> str:
    if not isinstance(ref, str):
        return ref
    path, sep, tail = ref.partition(";md5;")
    if path.startswith("../"):
        full = RAW + path[3:]
    elif path.startswith("./"):
        full = RAW + line_dir + "/" + path[2:]
    else:
        return ref
    return full + sep + tail


def build() -> dict:
    merged, online, local = [], [], []
    spider = ""
    for code, line_dir, label in LINES:
        cfg_path = os.path.join(APP_DIR, line_dir, "api.json")
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        for site in cfg.get("sites", []):
            s = dict(site)
            for k in ("api", "jar", "ext"):
                if k in s:
                    s[k] = abs_ref(s[k], line_dir)
            merged.append(s)
        if code == "std":
            spider = abs_ref(cfg.get("spider", ""), line_dir)
        online.append({"name": label, "url": RAW + line_dir + "/api.json"})
        local.append({"name": label, "url": f"clan://localhost/{LOCAL_ROOT}/{line_dir}/api.json"})
    return {
        "api_all.json": {"spider": spider, "wallpaper": "", "sites": merged,
                         "lives": [], "parses": [], "flags": []},
        "api_index.json": {"urls": online},
        "api_index_local.json": {"urls": local},
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
    ns = ap.parse_args()

    problems = self_check()
    out = build()
    counts = {line: len(json.load(open(os.path.join(APP_DIR, line, "api.json"), encoding="utf-8"))["sites"])
              for _c, line, _l in LINES}
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
    changed = [n for n in ("api_index.json", "api_index_local.json", "api_all.json")
               if write_if_changed(n, out[n])]
    print("已更新:", changed or "无变化")
    return 0


if __name__ == "__main__":
    sys.exit(main())
