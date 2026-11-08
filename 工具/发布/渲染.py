"""按平台渲染对外地址产物，并提供跨平台地址门禁。

用法（仓库根执行）：
    python 工具/发布/渲染.py --platform github
    python 工具/发布/渲染.py --platform gitee --owner <Gitee 个性地址>
    python 工具/发布/渲染.py --check --platform github      # 只校验，不写文件

渲染对象：
    apps/tvbox/api_index.json   ← 工具/源生成/生成.py 按平台重算
    apps/tvbox/api_all.json     ← 同上
    地址.md                     ← 地址模板.md 渲染（两平台并列，内容与平台无关）
    README.md / apps/*/README.md ← 受管地址块（标记之间由本脚本注入）

两平台完全一致、不渲染的文件：
    使用/*.md / 规范/*.md 只写仓库内相对路径，绝对地址一律指向 地址.md
    （见 规范/仓库通用规范.md 3.5 双平台地址维护）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM_FILE = os.path.join(REPO, "规则", "平台地址.json")
TEMPLATE = os.path.join(REPO, "地址模板.md")
ADDRESS = os.path.join(REPO, "地址.md")
GEN = os.path.join(REPO, "工具", "源生成", "生成.py")

# 受管地址块标记：标记之间的行由本脚本写入，其他行一律手写
BLOCK_START = "<!-- 地址块开始：由 工具/发布/渲染.py 生成，勿手改 -->"
BLOCK_END = "<!-- 地址块结束 -->"
BLOCK_FILES = ["README.md", "apps/tvbox/README.md", "apps/catmovie/README.md", "apps/reading/README.md"]

# 文档里禁止出现的「本仓绝对地址」：一律改相对路径或走受管地址块
BANNED = [
    re.compile(r"raw\.githubusercontent\.com/SL-learn/SL-Sources"),
    re.compile(r"cdn\.jsdelivr\.net/gh/SL-learn/SL-Sources"),
    re.compile(r"gitee\.com/[^\s`)'\"<>]*/SL-Sources"),
]
# 平台互斥：除受管地址块外，用户文档不得出现另一平台域名
CROSS = {
    "gitee": [re.compile(r"raw\.githubusercontent\.com"), re.compile(r"cdn\.jsdelivr\.net")],
    "github": [re.compile(r"gitee\.com")],
}
# 平台互斥只对「给人看的用户文档」生效
USER_GLOBS = ["README.md", "发布说明.md", "使用/*.md", "apps/*/README.md", "apps/tvbox/目录说明.txt"]
DOC_GLOBS = USER_GLOBS + ["声明.md", "文档索引.md", "规范/*.md"]

# Gitee 上被 451 拦截、不得作为可用地址列出的路径（与 规则/平台地址.json 的「受限路径」一致）
BLOCKED_PATHS = ["apps/tvbox/std/api.json", "apps/reading/书源.json", "apps/reading/订阅源.json"]


def load_platforms(owner: str = "") -> dict:
    """读全部平台基址；owner 只覆盖 Gitee 的 {owner} 占位。"""
    with open(PLATFORM_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    out = {}
    for code, p in cfg["平台"].items():
        own = p.get("owner") or os.environ.get("GITEE_OWNER", "")
        if not own:
            raise SystemExit(f"{p['名称']} 的 owner 未配置：改 规则/平台地址.json 或用 --owner 传入")
        if code == "gitee" and owner:
            own = owner
        q = {k: (v.replace("{owner}", own) if isinstance(v, str) else v) for k, v in p.items()}
        q["代号"] = code
        out[code] = q
    return out


def addr(p: dict, path: str) -> str:
    return p["raw"] + "/" + path


def render_address(plats: dict) -> str:
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    gh, ge = plats["github"], plats["gitee"]
    jsd = gh.get("jsDelivr") or ""
    if jsd:
        jsd_line = (f"- GitHub 侧 jsDelivr 加速（只下发 JSON，jar 会 403）：`{jsd}/apps/tvbox/api_all.json`\n"
                    f"- 固定版本：`{gh['jsDelivr模板'].replace('{ref}', '<tag 或完整 SHA>')}/apps/tvbox/api_all.json`\n"
                    "- Gitee 侧无 jsDelivr 加速，只用 raw。")
    else:
        jsd_line = "- 两平台都只用 raw。"
    subs = {
        "{{GITHUB_RAW}}": gh["raw"],
        "{{GITHUB_REF}}": gh["raw模板"].replace("{ref}", "tvbox-v2.4.0"),
        "{{GITHUB_网页}}": gh["网页"],
        "{{GITEE_RAW}}": ge["raw"],
        "{{GITEE_REF}}": ge["raw模板"].replace("{ref}", "tvbox-v2.4.0"),
        "{{GITEE_网页}}": ge["网页"],
        "{{JSDELIVR_LINE}}": jsd_line,
    }
    text = tpl
    for k, v in subs.items():
        text = text.replace(k, v)
    left = sorted(set(re.findall(r"\{\{[A-Za-z_\u4e00-\u9fff]+\}\}", text)))
    if left:
        raise SystemExit(f"地址模板有未替换占位符：{left}")
    return text


def _cell_blocked(p: dict, path: str) -> str:
    if path in p.get("受限路径", {}):
        return "451 拦截，暂不可用"
    return "`" + addr(p, path) + "`"


def render_blocks(plats: dict) -> dict:
    """生成各 README 的受管地址块（两平台并列，内容与渲染平台无关）。"""
    gh, ge = plats["github"], plats["gitee"]

    def row(app: str, entry: str, path: str) -> str:
        return f"| {app} | {entry} | `{addr(gh, path)}` | {_cell_blocked(ge, path)} |"

    root = [
        BLOCK_START,
        "| 应用 | 填到软件哪个入口 | GitHub 地址 | Gitee 地址 |",
        "|---|---|---|---|",
        row("TVBox / 影视仓", "设置 → 配置地址（多仓索引，推荐）", "apps/tvbox/api_index.json"),
        row("TVBox / 影视仓", "设置 → 配置地址（单文件全量 64 站）", "apps/tvbox/api_all.json"),
        "| TVBox / 影视仓 | 本地整包：整包放 `/sdcard/TVBox/tvbox/` 后填 | `clan://localhost/tvbox/api_index_local.json` | 同 GitHub |",
        row("小猫影视", "设置 → 订阅配置（单文件）", "apps/catmovie/config.json"),
        row("阅读", "书源管理 → 网络导入（书源 111 条）", "apps/reading/书源.json"),
        row("阅读", "订阅 → 网络导入（订阅源 26 条）", "apps/reading/订阅源.json"),
        "",
        "> 阅读的书源与订阅源是**两类分别导入**：先在「书源管理」填书源地址，再在「订阅」填订阅源地址。",
        "> Gitee 的 `apps/tvbox/std/api.json`、`apps/reading/书源.json`、`apps/reading/订阅源.json` 被 451 拦截，"
        "TVBox 用 `api_all.json`，阅读改用 GitHub 地址。完整表格与百分号编码写法见 [地址.md](./地址.md)。",
        BLOCK_END,
    ]
    tvbox = [
        BLOCK_START,
        "| 场景 | 填到软件哪个入口 | GitHub 地址 | Gitee 地址 |",
        "|---|---|---|---|",
        row("在线多线路", "设置 → 配置地址", "apps/tvbox/api_index.json"),
        row("单文件全量", "设置 → 配置地址", "apps/tvbox/api_all.json"),
        "| 本地整包 | 整包放 `/sdcard/TVBox/tvbox/` 后填 | `clan://localhost/tvbox/api_index_local.json` | 同 GitHub |",
        "",
        "> Gitee 版索引三条线路统一指向 `api_all.json`，因为 `apps/tvbox/std/api.json` 被 451 拦截。"
        "三条线路单独加载的地址见仓库根 [地址.md](../../地址.md)。",
        BLOCK_END,
    ]
    catmovie = [
        BLOCK_START,
        "| 平台 | 填到软件哪个入口 | 地址 |",
        "|---|---|---|",
        f"| GitHub | 设置 → 订阅配置（单文件） | `{addr(gh, 'apps/catmovie/config.json')}` |",
        f"| Gitee | 设置 → 订阅配置（单文件） | `{addr(ge, 'apps/catmovie/config.json')}` |",
        BLOCK_END,
    ]
    reading = [
        BLOCK_START,
        "| 类别 | 填到软件哪个入口 | GitHub 地址 | Gitee 地址 |",
        "|---|---|---|---|",
        row("书源（111 条）", "书源管理 → 网络导入", "apps/reading/书源.json"),
        row("订阅源（26 条）", "订阅 → 网络导入", "apps/reading/订阅源.json"),
        "",
        "> 书源与订阅源**分两次导入**，两个地址各填一次，不能合并成一个包。"
        "Gitee 侧两个文件都被 451 拦截，暂只能用 GitHub 地址或下载文件后本地导入。",
        BLOCK_END,
    ]
    return {
        "README.md": "\n".join(root),
        "apps/tvbox/README.md": "\n".join(tvbox),
        "apps/catmovie/README.md": "\n".join(catmovie),
        "apps/reading/README.md": "\n".join(reading),
    }


def inject_block(path: str, block: str) -> bool:
    """把受管块写入标记之间；标记缺失时报错，不猜插入位置。"""
    rel = os.path.relpath(path, REPO).replace("\\", "/")
    text = open(path, encoding="utf-8").read()
    if BLOCK_START not in text or BLOCK_END not in text:
        raise SystemExit(f"{rel} 缺少受管地址块标记（{BLOCK_START} / {BLOCK_END}）")
    head, rest = text.split(BLOCK_START, 1)
    _, tail = rest.split(BLOCK_END, 1)
    new = head + block + tail
    if new == text:
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    return True


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


def check(plats: dict, platform: str) -> list[str]:
    problems = []
    p = plats[platform]
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
        in_block = False
        for no, line in enumerate(open(path, encoding="utf-8"), 1):
            if BLOCK_START in line:
                in_block = True
                continue
            if BLOCK_END in line:
                in_block = False
                continue
            if in_block:
                continue
            if any(rx.search(line) for rx in BANNED):
                problems.append(f"{rel}:{no} 写死了仓库绝对地址，应改相对路径、受管地址块或指向 地址.md")
            elif is_user_doc and any(rx.search(line) for rx in CROSS.get(platform, [])):
                problems.append(f"{rel}:{no} 出现另一平台域名（受管地址块之外）")

    if not os.path.exists(ADDRESS):
        problems.append("地址.md 不存在：先跑 python 工具/发布/渲染.py --platform " + platform)
    else:
        text = open(ADDRESS, encoding="utf-8").read()
        for code, q in plats.items():
            if q["raw"] not in text:
                problems.append(f"地址.md 缺 {q['名称']} 的 raw 基址（{q['raw']}）")
        if "## 四、" in text:
            head, tail = text.split("## 四、", 1)
            parts = re.split(r"\n## ", tail, maxsplit=1)
            rest = parts[1] if len(parts) > 1 else ""
            outside = head + rest
            for blocked in BLOCKED_PATHS:
                if addr(plats["gitee"], blocked) in outside:
                    problems.append(f"地址.md 把 Gitee 的 451 路径当可用地址列出（{blocked}）")

    expected = render_blocks(plats)
    for rel_path, block in expected.items():
        full = os.path.join(REPO, rel_path)
        if not os.path.exists(full):
            problems.append(f"{rel_path} 不存在")
            continue
        text = open(full, encoding="utf-8").read()
        if BLOCK_START not in text or BLOCK_END not in text:
            problems.append(f"{rel_path} 缺少受管地址块标记")
        else:
            actual = BLOCK_START + text.split(BLOCK_START, 1)[1].split(BLOCK_END, 1)[0] + BLOCK_END
            if actual != block:
                problems.append(f"{rel_path} 受管地址块已过期，重跑渲染")

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

    plats = load_platforms(ns.owner)
    if ns.platform not in plats:
        raise SystemExit(f"未知平台：{ns.platform}（可选 {sorted(plats)}）")
    p = plats[ns.platform]

    if ns.check:
        problems = check(plats, ns.platform)
        print(f"平台：{p['名称']}（{p['代号']}）raw 基址：{p['raw']}")
        if problems:
            print("门禁不通过：")
            for x in problems:
                print(" -", x)
            return 1
        print("门禁通过：文档无跨平台地址、地址.md 与 README 地址块均为最新")
        return 0

    rc = run_generate(ns.platform, ns.owner)
    if rc != 0:
        print("生成失败，未渲染 地址.md")
        return rc
    changed = write_text(ADDRESS, render_address(plats))
    blocks = render_blocks(plats)
    for rel_path, block in blocks.items():
        full = os.path.join(REPO, rel_path)
        if os.path.exists(full):
            inject_block(full, block)
    print(f"平台：{p['名称']}（{p['代号']}）")
    print("地址.md:", "已更新" if changed else "无变化")
    problems = check(plats, ns.platform)
    if problems:
        print("渲染后门禁不通过：")
        for x in problems:
            print(" -", x)
        return 1
    print("渲染完成，门禁通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
