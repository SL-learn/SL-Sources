# 便携版导出：把 apps/{tvbox,catmovie,reading} 的最小可运行集导出为「整包」
#
# 用法（仓库根执行）：
#   python 工具/发布/导出云端.py
#   python 工具/发布/导出云端.py --out D:\某目录 --no-zip
#
# 机制（对应 规范/仓库通用规范.md SYS-DIST-012）：
#   1) 复制最小可运行集，产物目录全 ASCII；
#   2) 把 api_all.json 内所有指向本仓的自指绝对地址重写为 ./ 相对写法；
#   3) 导出后硬性扫描：命中本仓自指平台地址即失败；jar/spider 出现 http 即失败；
#   4) 生成 文件指纹.txt（sha256）与 地址-便携版.txt，并打包 zip。
#
# 导出产物不进入 git 仓库（默认输出到仓库外的 发布/云端）。

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
APPS = os.path.join(REPO, 'apps')

SELF_PREFIXES = [
    'https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/',
    'https://raw.githubusercontent.com/SL-learn/SL-Sources/main/',
    'https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/tvbox/',
    'https://gitee.com/gerenxiuxian/SL-Sources/raw/main/',
    'https://cdn.jsdelivr.net/gh/SL-learn/SL-Sources@main/apps/tvbox/',
    'https://cdn.jsdelivr.net/gh/SL-learn/SL-Sources@main/',
    'https://github.com/SL-learn/SL-Sources/blob/main/apps/tvbox/',
    'https://github.com/SL-learn/SL-Sources/blob/main/',
]

SELF_PATTERNS = [
    'raw.githubusercontent.com/SL-learn/SL-Sources',
    'gitee.com/gerenxiuxian/SL-Sources',
    'github.com/SL-learn/SL-Sources',
    'cdn.jsdelivr.net/gh/SL-learn/SL-Sources',
]

THIRD_PARTY_RE = re.compile(
    r'https?://[^\s"\',;`\\]*(?:raw\.githubusercontent\.com|gitee\.com|github\.com)[^\s"\',;`\\]*'
)

TEXT_EXT = {'.json', '.js', '.txt', '.md', '.csv', '.py', '.yaml', '.yml', '.ini', '.conf'}

# 内容快照：运行时加载的上游数据，导出时抓成本地文件并改写为相对引用
LIVE_SNAPSHOTS = [
    ('https://gh-proxy.com/https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.m3u', 'vbskycn_iptv4.m3u'),
    ('https://gh-proxy.com/https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u', 'aptv_iptv.m3u'),
    ('https://gh-proxy.com/https://raw.githubusercontent.com/wwb521/live/refs/heads/main/tv.m3u', 'wwb521_tv.m3u'),
    ('https://gh-proxy.com/https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u', 'suxuang_ipv4.m3u'),
]

BILI_SNAPSHOTS = [
    ('哔哩哔哩小品', 'bili_xiaopin.json'),
    ('哔哩哔哩相声', 'bili_xiansheng.json'),
    ('哔哩哔哩戏曲', 'bili_xiqu.json'),
]
BILI_BASE = 'https://raw.githubusercontent.com/tushen6/Tomorrow/master/json/'

DRPY_PLACEHOLDER = 'https://ghproxy.net/https://raw.githubusercontent.com/hjdhnx/dr_py/main/404.jpg'
BILI_COOKIE_REMOTE = 'https://ghproxy.net/https://raw.githubusercontent.com/FongMi/CatVodSpider/main/txt/cookie.txt'

# 注释/版权声明里的地址：保留原样，不属运行时依赖
COMMENT_URLS = {
    'https://github.com/nodeca/pako',
    'https://github.com/zloirock/core-js/issues/86#issuecomment-115759028',
    'https://github.com/sstur/jinja-js',
    'https://github.com/FongMi/Release/tree/main/apk',
    'https://ghproxy.net/https://raw.githubusercontent.com/UndCover/PyramidStore/main/list.md',
    'https://github.com/ch6vip/fqapp',
    'https://gitee.com/visita/yd/raw/master/06red/0purple.jpg',
    'https://gitee.com/visita/yd/raw/master/06red/004.png',
}

# 运行时仍保留、但已确认无法以相对路径本地化的地址（仅图标，不影响内容抓取）
ICON_EXCEPTIONS = {
    'https://gitee.com/visita/yd/raw/master/00rose/${src}',
    'https://gitee.com/visita/yd/raw/master/01pink/${src}',
    'https://gitee.com/visita/yd/raw/master/02blue/${src}',
    'https://gitee.com/visita/yd/raw/master/03green/${src}',
    'https://gitee.com/visita/yd/raw/master/04gear/${src}',
    'https://gitee.com/visita/yd/raw/master/05green/${src}',
    'https://gitee.com/visita/yd/raw/master/06red/${src}',
    'https://gitee.com/visita/yd/raw/master/07blackred/${src}',
    'https://gitee.com/visita/yd/raw/master/08black/${src}',
    'https://gitee.com/visita/yd/raw/master/09note/${src}',
}


def log(msg):
    print(msg, flush=True)


def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path, data):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))


def copy_tree(src, dst):
    if not os.path.exists(src):
        return 0
    if os.path.isdir(src):
        shutil.copytree(src, dst)
        return 1
    shutil.copy2(src, dst)
    return 1


def copy_minimal(out_root):
    tv_src = os.path.join(APPS, 'tvbox')
    tv_dst = os.path.join(out_root, 'tvbox')
    os.makedirs(tv_dst, exist_ok=True)

    for name in ['api_index_rel.json', 'api_index_local.json', 'version.json', '目录说明.txt', '更新时间.txt']:
        src = os.path.join(tv_src, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(tv_dst, name))

    for d in ['std', 'kids', 'elders', '_common']:
        src = os.path.join(tv_src, d)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(tv_dst, d))

    # api_all.json 重写为相对引用后再写包内
    api_all_src = os.path.join(tv_src, 'api_all.json')
    if os.path.exists(api_all_src):
        with open(api_all_src, 'r', encoding='utf-8') as f:
            text = f.read()
        for p in SELF_PREFIXES:
            text = text.replace(p, './')
        data = json.loads(text)
        write_json(os.path.join(tv_dst, 'api_all.json'), data)

    for app in ['catmovie', 'reading']:
        src_dir = os.path.join(APPS, app)
        dst_dir = os.path.join(out_root, app)
        if not os.path.isdir(src_dir):
            continue
        os.makedirs(dst_dir, exist_ok=True)
        for name in os.listdir(src_dir):
            if name.lower().endswith(('.md', '.png', '.jpg')):
                continue
            s = os.path.join(src_dir, name)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(dst_dir, name))


def real_url(url):
    for proxy in ('https://gh-proxy.com/', 'https://g.blfrp.cn/'):
        if url.startswith(proxy):
            return url[len(proxy):]
    return url


def url_candidates(url):
    direct = real_url(url)
    cands = [url, direct]
    for proxy in ('https://gh-proxy.com/', 'https://g.blfrp.cn/'):
        cands.append(proxy + direct)
    return list(dict.fromkeys(cands))


def fetch_file(url, dst, cache_dir):
    key = hashlib.sha1(url.encode('utf-8')).hexdigest()
    cached = os.path.join(cache_dir, key)
    if not os.path.exists(cached):
        last = None
        for cand in url_candidates(url):
            for _ in range(2):
                try:
                    req = urllib.request.Request(
                        urllib.parse.quote(cand, safe=':/?&=@'),
                        headers={'User-Agent': 'Mozilla/5.0'},
                    )
                    tmp = cached + '.tmp'
                    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, 'wb') as f:
                        f.write(r.read())
                    os.replace(tmp, cached)
                    last = None
                    break
                except Exception as e:
                    last = e
                    time.sleep(2)
            if last is None:
                break
        if last is not None:
            raise RuntimeError(f'抓取失败：{url}（{last}）')
    shutil.copyfile(cached, dst)
    return os.path.getsize(dst)


def localize(out_root, cache_dir):
    """抓取运行时上游依赖到包内，并改写为相对引用；返回替换清单。"""
    rows = []
    os.makedirs(cache_dir, exist_ok=True)

    # 1) 小猫影视直播源 m3u -> catmovie/live/
    cfg_path = os.path.join(out_root, 'catmovie', 'config.json')
    if os.path.exists(cfg_path):
        cfg = read_json(cfg_path)
        live_dir = os.path.join(out_root, 'catmovie', 'live')
        os.makedirs(live_dir, exist_ok=True)
        for item in cfg.get('lives', []):
            url = str(item.get('url', ''))
            for src, name in LIVE_SNAPSHOTS:
                if url == src:
                    size = fetch_file(src, os.path.join(live_dir, name), cache_dir)
                    item['url'] = f'./live/{name}'
                    rows.append(('内容快照', src, f'catmovie/live/{name}', size))
                    break
            else:
                if url.startswith('http'):
                    raise RuntimeError(f'未登记的上游直播源，拒绝未本地化：{url}')
        write_json(cfg_path, cfg)

    # 2) 哔哩 ext json -> tvbox/_common/content/bili/
    bili_dir = os.path.join(out_root, 'tvbox', '_common', 'content', 'bili')
    os.makedirs(bili_dir, exist_ok=True)
    names = {}
    for zh, name in BILI_SNAPSHOTS:
        src = BILI_BASE + zh + '.json'
        size = fetch_file(src, os.path.join(bili_dir, name), cache_dir)
        rows.append(('内容快照', src, f'tvbox/_common/content/bili/{name}', size))
        names[zh] = name

    def bili_name(url):
        text = urllib.parse.unquote(url)
        for zh, name in names.items():
            if text.endswith(zh + '.json'):
                return name
        return None

    for rel, prefix in [
        ('tvbox/elders/api.json', '../_common/content/bili/'),
        ('tvbox/api_all.json', './_common/content/bili/'),
    ]:
        path = os.path.join(out_root, rel)
        if not os.path.exists(path):
            continue
        data = read_json(path)
        for site in data.get('sites', []):
            ext = site.get('ext')
            if isinstance(ext, dict) and str(ext.get('json', '')).startswith('http'):
                name = bili_name(str(ext['json']))
                if not name:
                    raise RuntimeError(f'{rel}: 未登记的上游 ext json，拒绝未本地化：{ext["json"]}')
                rows.append(('本地化改写', str(ext['json']), f'tvbox/_common/content/bili/{name}', 0))
                ext['json'] = prefix + name
        write_json(path, data)

    # 3) drpy 引擎内置远程占位图改空值（客户端图片加载器不接受相对路径）
    placeholder = f'"{DRPY_PLACEHOLDER}"'
    removed = 0
    for rel in [
        'tvbox/std/js/drpy2.min.js',
        'tvbox/std/ext/drpy2.min.js',
        'tvbox/std/lib/drpy2.min.js',
        'tvbox/kids/api/drpy2.min.js',
        'tvbox/elders/api/huban_drpy2.min.js',
        'tvbox/elders/api/jiduo_drpy2.min.js',
        'tvbox/std/lib/哔哩直播.js',
    ]:
        path = os.path.join(out_root, rel)
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        n = text.count(placeholder)
        if n:
            removed += n
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(text.replace(placeholder, '""'))
    if removed:
        rows.append(('运行时移除', DRPY_PLACEHOLDER, '（无数据占位图改为空值）', 0))

    # 4) 哔哩直播 Cookie：远程 txt 改环境变量
    js = os.path.join(out_root, 'tvbox/std/lib/哔哩直播.js')
    if os.path.exists(js):
        with open(js, 'r', encoding='utf-8') as f:
            text = f.read()
        if BILI_COOKIE_REMOTE in text:
            with open(js, 'w', encoding='utf-8', newline='') as f:
                f.write(text.replace(f'"Cookie":"{BILI_COOKIE_REMOTE}"', '"Cookie":"$bili_cookie"'))
            rows.append(('运行时移除', BILI_COOKIE_REMOTE, '（改为 $bili_cookie 环境变量）', 0))

    return rows


def collect_text_files(root):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                yield os.path.join(dirpath, fn)


def scan(out_root):
    """扫描分四类：自指/绝对字段失败、运行时未本地化失败、注释声明、运行时例外。"""
    failures = []
    comments = []
    exceptions = []
    runtime = []
    for path in collect_text_files(out_root):
        rel = os.path.relpath(path, out_root).replace(os.sep, '/')
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        except Exception as e:
            failures.append(f'{rel}: 读取失败 {e}')
            continue
        for pat in SELF_PATTERNS:
            if pat in text:
                failures.append(f'{rel}: 命中自指平台地址 {pat}')
        for m in THIRD_PARTY_RE.findall(text):
            if m in COMMENT_URLS:
                comments.append((rel, m))
            elif m in ICON_EXCEPTIONS:
                exceptions.append((rel, m))
            else:
                runtime.append((rel, m))

    # 运行时字段：直播源与 ext json 必须是包内相对引用
    cfg = os.path.join(out_root, 'catmovie', 'config.json')
    if os.path.exists(cfg):
        for item in read_json(cfg).get('lives', []):
            u = str(item.get('url', ''))
            if u.startswith('http'):
                failures.append(f'catmovie/config.json: 直播源仍为远程地址 {u[:120]}')
    for name in ['tvbox/api_all.json', 'tvbox/elders/api.json']:
        path = os.path.join(out_root, name)
        if not os.path.exists(path):
            continue
        for site in read_json(path).get('sites', []):
            ext = site.get('ext')
            if isinstance(ext, dict) and str(ext.get('json', '')).startswith('http'):
                failures.append(f'{name}: ext json 仍为远程地址 {ext["json"][:120]}')

    for name in ['tvbox/api_all.json', 'tvbox/api_index_rel.json'] + [
        f'tvbox/{d}/api.json' for d in ('std', 'kids', 'elders')
    ]:
        path = os.path.join(out_root, name)
        if not os.path.exists(path):
            continue
        data = read_json(path)
        for field in ['spider', 'jar']:
            if field == 'spider' and isinstance(data.get('spider', ''), str):
                vals = [data.get('spider', '')]
            else:
                vals = [str(s.get('jar', '')) for s in data.get('sites', []) if s.get('jar')]
            for v in vals:
                if v.startswith('http'):
                    failures.append(f'{name}: {field} 仍为绝对地址 {v[:120]}')
    return failures, comments, exceptions, runtime


def write_fingerprint(out_root, version):
    rows = []
    for dirpath, _, filenames in os.walk(out_root):
        for fn in filenames:
            if fn == '文件指纹.txt':
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, out_root).replace(os.sep, '/')
            h = hashlib.sha256()
            with open(p, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    h.update(chunk)
            rows.append((rel, h.hexdigest(), os.path.getsize(p)))
    rows.sort()
    total = sum(r[2] for r in rows)
    lines = [f'# TVBox 便携版 版本={version} 生成={datetime.now():%Y-%m-%d %H:%M} 文件数={len(rows)} 总字节={total}']
    lines += [f'{h}  {rel}' for rel, h, _ in rows]
    with open(os.path.join(out_root, '文件指纹.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    return len(rows), total


def write_readme(out_root, version, total, count, rows):
    items = []
    seen = set()
    for kind, src, dst, size in rows:
        key = (src, dst)
        if key in seen:
            continue
        seen.add(key)
        size_text = f'{size} 字节' if size else '—'
        items.append(f'      {kind}：{src} → {dst}（{size_text}）')
    items_text = '\n'.join(items) if items else '      （本次无需本地化）'
    body = f"""TVBox 便携版（{version}）

一、入口文件（唯一）
    tvbox/api_index_rel.json
    - 索引里的三条线路都是 ./ 相对地址，整包换存放位置不用重新生成。
    - 上传后直接把这个文件的直链填进软件；不要只传索引、不传线路目录。

二、上传后填到哪个软件的哪个入口
    TVBox / 影视仓   设置 → 配置地址                        <存放位置>/tvbox/api_index_rel.json
    TVBox / 影视仓   设置 → 配置地址（64 站单文件，可选）    <存放位置>/tvbox/api_all.json
    小猫影视         设置 → 订阅配置                        <存放位置>/catmovie/config.json
    阅读             书源管理 → 网络导入（书源 111 条）      <存放位置>/reading/书源.json
    阅读             订阅 → 网络导入（订阅源 26 条）         <存放位置>/reading/订阅源.json

    阅读的书源与订阅源是两类分别导入，不能合并成一个包。
    若平台不接受中文文件名，把 reading 的两个地址改成百分号编码（与上面等价）：
      书源：<存放位置>/reading/%E4%B9%A6%E6%BA%90.json
      订阅源：<存放位置>/reading/%E8%AE%A2%E9%98%85%E6%BA%90.json

三、包内目录对应关系
    tvbox/
      api_index_rel.json    入口（相对索引）
      api_index_local.json  本地兜底索引
      api_all.json          64 站单文件（绝对引用已重写为 ./）
      version.json、目录说明.txt、更新时间.txt
      std/ kids/ elders/    三条线路：api.json + spider.jar + api/ js/ lib/ ext/ open/
      _common/jar/          公共 jar，被线路用 ../_common/jar/ 引用
      _common/content/bili/ 哔哩 ext json 内容快照（3 个）
    catmovie/  config.json、version.json、更新时间.txt、live/（4 个直播源 m3u 快照）
    reading/   书源.json、订阅源.json、version.json、更新时间.txt

四、不能改名或移动位置（改了必然加载失败）
    - tvbox/api_index_rel.json：文件名和所在目录都不能改，三条线路地址按它的位置解析。
    - tvbox/std、tvbox/kids、tvbox/elders：目录名与其中的 api.json 文件名不能改；
      api.json 里的 ./spider.jar 与 ../_common/jar/ 都是相对写法。
    - tvbox/_common 必须与三条线路同级（即 tvbox/_common），不能挪进 std/ 里。
    - 线路内的 api/、js/、lib/、ext/、open/、spider.jar 必须整体保留，不能只挑单个文件上传。
    - catmovie/config.json、reading/书源.json、reading/订阅源.json 的文件名不要改，
      改名后在线地址要跟着换。

五、本地兜底入口（不上传时）
    把 tvbox/ 整个目录放到客户端根目录下（多数客户端根为 /sdcard，即 /sdcard/tvbox/），
    入口填：clan://localhost/tvbox/api_index_rel.json
    本包不含 451 受限文件，本地入口不依赖任何平台地址。

    相对路径支持：索引、线路 api、spider.jar、ext json 的 ./ 与 ../ 由客户端按配置地址
    解析（已按客户端源码核对，未在真机实测）。实机一眼判断：能加载出三条线路即索引生效；
    打开任一线路能看到站点列表即相对线路与 JS 生效；日志出现 spider 或 ext 路径不存在，
    说明存放位置没有保持本包目录结构。

六、校验
    文件指纹.txt 是 sha256 清单（文件数 {count}，总字节 {total}），解压后可逐行重算比对。
    存放位置必须能直接取回文件本体（不是 HTML 分享页），并保持本包目录结构。

七、本地化与内容快照（本包不依赖任何远程仓库）
    已本地化 / 快照项（原地址 → 包内路径 → 大小）：
{items_text}
    快照抓取时间：{datetime.now():%Y-%m-%d %H:%M}
    刷新方式：重跑 `python 工具/发布/导出云端.py`，脚本会重新抓取并重写相对引用；
    索引只含相对路径，刷新快照后不需要重新生成索引。
    运行时移除（不产生文件）：
      - drpy 无数据占位图 404.jpg：改为空值（客户端图片加载器不接受相对路径，该图仅缺省展示）。
      - 哔哩直播 Cookie：改为 $bili_cookie 环境变量（需要登录态时请在客户端环境变量配置）。
    未本地化例外（仅图标，不影响内容抓取）：
      阅读订阅源第 25 项的封面图标由 @js 按文件名动态拼接 gitee 目录（00rose~09note 共 10 个基址），
      图标集合不可穷举，且阅读端图片加载器要求绝对地址，改相对路径无法解析，故保留原样。

生成时间：{datetime.now():%Y-%m-%d %H:%M}
"""
    with open(os.path.join(out_root, '地址-便携版.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)


def make_zip(out_root, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dirpath, _, filenames in os.walk(out_root):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, out_root).replace(os.sep, '/')
                z.write(p, rel)


def main():
    ap = argparse.ArgumentParser()
    default_out = os.path.join(os.path.dirname(REPO), '发布', '云端')
    ap.add_argument('--out', default=default_out, help='导出根目录（默认 仓库外 发布/云端）')
    ap.add_argument('--no-zip', action='store_true', help='不生成 zip')
    args = ap.parse_args()

    version = read_json(os.path.join(APPS, 'tvbox', 'version.json'))['version']
    out_root = os.path.join(args.out, f'TVBox-便携版-{version}')
    if os.path.exists(out_root):
        shutil.rmtree(out_root)
    os.makedirs(out_root)

    log(f'仓库：{REPO}')
    log(f'版本：{version}')
    log(f'输出：{out_root}')

    copy_minimal(out_root)

    cache_dir = os.path.join(args.out, '.cache', '本地化')
    try:
        rows = localize(out_root, cache_dir)
    except Exception as e:
        log('')
        log(f'本地化失败：{e}')
        return 1

    log('')
    log('==== 本地化与内容快照 ====')
    seen = set()
    for kind, src, dst, size in rows:
        key = (src, dst)
        if key in seen:
            continue
        seen.add(key)
        size_text = f'{size} 字节' if size else '—'
        log(f'  {kind}：{src} → {dst}（{size_text}）')

    failures, comments, exceptions, runtime = scan(out_root)
    if runtime:
        failures += [f'{rel}: 运行时引用未本地化 {url}' for rel, url in runtime]

    log('')
    log('==== 扫描结果 ====')
    log(f'自指平台地址：{"0 命中" if not any("自指" in f for f in failures) else "命中"}')
    log(f'jar/spider 绝对地址：{"0 命中" if not any("绝对地址" in f for f in failures) else "命中"}')
    log(f'运行时引用未本地化：{len(runtime)} 处')
    log(f'注释/声明（保留原样）：{len(comments)} 处')
    log(f'运行时例外（仅图标，单列说明）：{len(exceptions)} 处')
    if failures:
        for f in failures:
            log('失败：' + f)

    if failures:
        log('')
        log('导出失败：存在未本地化的运行时引用或绝对地址，未生成指纹与 zip。')
        return 1

    count, total = write_fingerprint(out_root, version)
    write_readme(out_root, version, total, count, rows)

    zip_path = ''
    if not args.no_zip:
        zip_path = os.path.join(args.out, f'TVBox-便携版-{version}.zip')
        make_zip(out_root, zip_path)

    log('')
    log(f'文件数：{count}　总字节：{total}')
    if zip_path:
        log(f'zip：{zip_path}（{os.path.getsize(zip_path)} 字节）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
