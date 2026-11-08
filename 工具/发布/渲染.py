"""按平台渲染对外地址产物，并提供跨平台地址门禁。

用法（仓库根执行）：
    python 工具/发布/渲染.py --platform github
    python 工具/发布/渲染.py --platform gitee --owner <Gitee 个性地址>
    python 工具/发布/渲染.py --check --platform github      # 只校验，不写文件

渲染对象（路径固定，内容随平台不同）：
    apps/tvbox/api_index.json   ← 工具/源生成/生成.py 按平台重算
    apps/tvbox/api_all.json     ← 同上
    地址.md                     ← 地址模板.md 渲染

两平台完全一致、不渲染的文件：
    README.md / 使用/*.md / apps/*/README.md / 规范/*.md 只写仓库内相对路径，
    绝对地址一律指向 地址.md（见 规范/仓库通用规范.md 3.5 双平台地址维护）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM_FILE = os.path.join(REPO, "规则", "平台地址.json")
TEMPLATE = os.path.join(REPO, "地址模板.md")
ADDRESS = os.path.join(REPO, "地址.md")
GEN = os.path.join(REPO, "工具", "源生成", "生成.py")

# 文档里禁止出现的「本仓绝对地址」：一律改相对路径或指向 地址.md
BANNED = [
    re.compile(r"raw\.githubusercontent\.com/SL-learn/SL-Sources"),
    re.compile(r"cdn\.jsdelivr\.net/gh/SL-learn/SL-Sources"),
    re.compile(r"gitee\.com/[^\s`)'\"<>]*/SL-Sources"),
]
# 平台互斥：gitee 版不得出现 GitHub 域名；github 版不得出现 Gitee 域名（README 的双远端章节只写平台名，不写域名）
CROSS = {
    "gitee": [re.compile(r"raw\.githubusercontent\.com"), re.compile(r"cdn\.jsdelivr\.net")],
    "github": [re.compile(r"gitee\.com")],
}
# 平台互斥只对「给人看的用户文档」生效：这些文件不得出现另一平台域名
# （规范/ 允许用 <owner>、<平台 raw 基址> 这类通用写法讨论两个平台）
USER_GLOBS = ["README.md", "发布说明.md", "使用/*.md", "apps/*/README.md", "apps/tvbox/目录说明.txt"]
DOC_GLOBS = USER_GLOBS + ["声明.md", "文档索引.md", "规范/*.md"]


def load_platform(platform: str, owner: str = "") -> dict:
    with open(PLATFORM_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    try:
        p = cfg["平台"][platform]
    except KeyError:
        raise SystemExit(f"未知平台：{platform}（可选 {sorted(cfg['平台'])}）")
    owner = owner or p.get("owner") or os.environ.get("GITEE_OWNER", "")
    if not owner:
        raise SystemExit(f"{p['名称']} 的 owner 未配置：用 --owner 或环境变量 GITEE_OWNER 传入")
    p = {k: (v.replace("{owner}", owner) if isinstance(v, str) else v) for k, v in p.items()}
    p["代号"] = platform
    return p


def render_address(p: dict) -> str:
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    jsd = p.get("jsDelivr") or ""
    if jsd:
        jsd_line = (f"- jsDelivr 加速（只下发 JSON，jar 会 403）：`{jsd}/apps/tvbox/api_all.json`\n"
                    f"- 固定版本：`{p['jsDelivr模板'].replace('{ref}', '<tag 或完整 SHA>')}/apps/tvbox/api_all.json`")
    else:
        jsd_line = "- 本平台无 jsDelivr 加速，只用 raw。"
    subs = {
        "{{平台名称}}": p["名称"],
        "{{平台代号}}": p["代号"],
        "{{RAW_BASE}}": p["raw"],
        "{{网页地址}}": p["网页"],
        "{{REF_RAW_BASE}}": p["raw模板"].replace("{ref}", "tvbox-v2.4.0"),
        "{{JSDELIVR_LINE}}": jsd_line,
        "{{渲染时间}}": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    text = tpl
    for k, v in subs.items():
        text = text.replace(k, v)
    left = sorted(set(re.findall(r"\{\{[A-Za-z_]+\}\}", text)))
    if left:
        raise SystemExit(f"地址模板有未替换占位符：{left}")
    return text


def write_text(path: str, text: str) -> bool:
    if os.path.exists(path) and open(path, encoding="utf-8").read() == text:
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def run_generate(platform: str, owner: str) -> int:
    cmd = [sys.executable, GEN, "--platform", platform]
    if owner:
        cmd += ["--owner", owner]
    return subprocess.call(cmd, cwd=REPO)


def check(p: dict) -> list[str]:
    problems = []
    files = []
    for pattern in DOC_GLOBS:
        files += sorted(glob.glob(os.path.join(REPO, pattern)))
    user_files = set()
    for pattern in USER_GLOBS:
        user_files.update(os.path.normcase(p) for p in glob.glob(os.path.join(REPO, pattern)))
    for path in sorted(set(files)):
        if not os.path.isfile(path) or path == ADDRESS:
            continue
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        is_user_doc = os.path.normcase(path) in user_files
        for no, line in enumerate(open(path, encoding="utf-8"), 1):
            if any(rx.search(line) for rx in BANNED):
                problems.append(f"{rel}:{no} 写死了仓库绝对地址，应改相对路径或指向 地址.md")
            elif is_user_doc and any(rx.search(line) for rx in CROSS.get(p["代号"], [])):
                problems.append(f"{rel}:{no} 出现另一平台域名")

    if not os.path.exists(ADDRESS):
        problems.append("地址.md 不存在：先跑 python 工具/发布/渲染.py --platform " + p["代号"])
    else:
        text = open(ADDRESS, encoding="utf-8").read()
        if p["raw"] not in text:
            problems.append(f"地址.md 不是 {p['名称']} 版本（缺 {p['raw']}）")
        for rx in CROSS.get(p["代号"], []):
            if rx.search(text):
                problems.append(f"地址.md 混入另一平台地址（{rx.pattern}）")

    idx = os.path.join(REPO, "apps", "tvbox", "api_index.json")
    if os.path.exists(idx):
        data = json.load(open(idx, encoding="utf-8"))
        urls = [u.get("url", "") for u in data.get("urls", [])]
        if not all(u.startswith(p["raw"] + "/") for u in urls):
            problems.append(f"apps/tvbox/api_index.json 未按 {p['名称']} 渲染（实际 {urls[:1]}）")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="github")
    ap.add_argument("--owner", default="")
    ap.add_argument("--check", action="store_true", help="只校验跨平台地址，不写文件")
    ns = ap.parse_args()

    p = load_platform(ns.platform, ns.owner)
    if ns.check:
        problems = check(p)
        print(f"平台：{p['名称']}（{p['代号']}）raw 基址：{p['raw']}")
        if problems:
            print("门禁不通过：")
            for x in problems:
                print(" -", x)
            return 1
        print("门禁通过：文档无跨平台地址、地址.md 与本平台一致")
        return 0

    rc = run_generate(ns.platform, ns.owner)
    if rc != 0:
        print("生成失败，未渲染 地址.md")
        return rc
    changed = write_text(ADDRESS, render_address(p))
    print(f"平台：{p['名称']}（{p['代号']}）")
    print("地址.md:", "已更新" if changed else "无变化")
    problems = check(p)
    if problems:
        print("渲染后门禁不通过：")
        for x in problems:
            print(" -", x)
        return 1
    print("渲染完成，门禁通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
