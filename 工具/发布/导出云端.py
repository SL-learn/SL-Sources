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
    r'https?://[^\s"\',;]*(?:raw\.githubusercontent\.com|gitee\.com|github\.com)[^\s"\',;]*'
)

TEXT_EXT = {'.json', '.js', '.txt', '.md', '.csv', '.py', '.yaml', '.yml', '.ini', '.conf'}


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


def collect_text_files(root):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                yield os.path.join(dirpath, fn)


def scan(out_root):
    failures = []
    third_party = []
    for path in collect_text_files(out_root):
        rel = os.path.relpath(path, out_root)
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
            third_party.append((rel, m[:160]))

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
    return failures, third_party


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


def write_readme(out_root, version, total, count):
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
    catmovie/  config.json、version.json、更新时间.txt
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

六、校验
    文件指纹.txt 是 sha256 清单（文件数 {count}，总字节 {total}），解压后可逐行重算比对。
    存放位置必须能直接取回文件本体（不是 HTML 分享页），并保持本包目录结构。

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
    failures, third_party = scan(out_root)

    log('')
    log('==== 扫描结果 ====')
    if failures:
        for f in failures:
            log('失败：' + f)
    else:
        log('自指平台地址：0 命中；jar/spider 绝对地址：0 命中')
    if third_party:
        log(f'第三方上游内容地址（不计失败）：{len(third_party)} 处')
        seen = set()
        for rel, url in third_party:
            key = (rel, url)
            if key in seen:
                continue
            seen.add(key)
            log(f'  {rel}: {url}')

    if failures:
        log('')
        log('导出失败：存在自指平台地址或 jar 绝对地址，未生成指纹与 zip。')
        return 1

    count, total = write_fingerprint(out_root, version)
    write_readme(out_root, version, total, count)

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
