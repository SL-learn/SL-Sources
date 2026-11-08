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

一、在线入口（上传到自选静态存放位置后）
    <存放位置>/tvbox/api_index_rel.json
    - 该索引内全部为 ./ 相对地址，换存放位置不需要重新生成。
    - 存放位置必须保持包内目录结构，且 api_index_rel.json 与 std/api.json 等文件可直接取回（不是 HTML 分享页）。

二、本地入口（兜底）
    解压后把 tvbox/ 整个目录放到客户端根目录下（多数客户端根为 /sdcard，即 /sdcard/tvbox/），
    入口填：clan://localhost/tvbox/api_index_rel.json
    Gitee 451 相关文件不在此包内，本地入口不依赖任何平台地址。

三、包内容
    tvbox/      api_index_rel.json、api_index_local.json、api_all.json（已重写为相对引用）、std/kids/elders、_common
    catmovie/   config.json
    reading/    书源.json、订阅源.json

四、校验
    文件指纹.txt 为 sha256 清单（文件数 {count}，总字节 {total}），解压后可逐行重算比对。

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
