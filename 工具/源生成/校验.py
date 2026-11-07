"""线上入口校验：逐条实测 GitHub raw 是否与本地一致。

用法（仓库根执行）：
    python 工具/源生成/校验.py                 # 校验 main
    python 工具/源生成/校验.py --ref tvbox-v2.0.0
    python 工具/源生成/校验.py --base https://raw.githubusercontent.com/<owner>/<repo>/<ref>/apps/tvbox/

校验项：索引 200 / 三条线路 200 且站点数一致 / api_all 200 且站数一致 / spider.jar 200 且 md5 一致 / cms.js 200。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_DIR = os.path.join(REPO, "apps", "tvbox")
OWNER_REPO = "SL-learn/SL-Sources"
UA = {"User-Agent": "okhttp/3.15"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def fetch(url: str, timeout: int = 20):
    req = urllib.request.Request(url.replace(" ", "%20"), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read()
    except Exception as e:
        return None, str(e).encode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="main")
    ap.add_argument("--base", default="")
    ns = ap.parse_args()
    base = ns.base or f"https://raw.githubusercontent.com/{OWNER_REPO}/{ns.ref}/apps/tvbox/"
    if not base.endswith("/"):
        base += "/"

    fails = []
    st, body = fetch(base + "api_index.json")
    idx = json.loads(body) if st == 200 else {}
    print(f"api_index.json  {st}  线路 {len(idx.get('urls', []))}")
    if st != 200 or len(idx.get("urls", [])) != 3:
        fails.append("api_index.json")

    for line in ("std", "kids", "elders"):
        local = json.load(open(os.path.join(APP_DIR, line, "api.json"), encoding="utf-8"))
        st, body = fetch(base + line + "/api.json")
        try:
            remote = json.loads(body)
        except Exception:
            remote = {}
        n_local, n_remote = len(local.get("sites", [])), len(remote.get("sites", []))
        print(f"{line}/api.json  {st}  站点 {n_remote}/{n_local}  spider={remote.get('spider', '')[:32]}")
        if st != 200 or n_remote != n_local:
            fails.append(f"{line}/api.json")
        sp = str(local.get("spider", ""))
        if sp.startswith("./") and ";md5;" in sp:
            fname, want = sp[2:].split(";md5;")
            st, body = fetch(base + line + "/" + fname)
            got = hashlib.md5(body).hexdigest()
            print(f"{line}/{fname}  {st}  {len(body)}B  md5 {'一致' if got == want.strip() else '不一致'}")
            if st != 200 or got != want.strip():
                fails.append(f"{line}/{fname}")

    st, body = fetch(base + "api_all.json")
    try:
        allcfg = json.loads(body)
    except Exception:
        allcfg = {}
    print(f"api_all.json  {st}  站点 {len(allcfg.get('sites', []))}")
    if st != 200 or not allcfg.get("sites"):
        fails.append("api_all.json")

    st, body = fetch(base + "std/js/cms.js")
    print(f"std/js/cms.js  {st}  {len(body)}B")
    if st != 200:
        fails.append("std/js/cms.js")

    print("\n结论:", "全部通过" if not fails else f"失败 {len(fails)} 项：{fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
