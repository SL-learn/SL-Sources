# TVBox 应用标准

> 文件位置：`apps/tvbox/README.md`
> 地位：TVBox 应用的**应用级**说明；通用纪律（命名、门禁、探活、验收、记录）一律以仓库根 `README.md` 为准，本文只写 TVBox 特有的加载机制与入口写法。
> 条款引用：本文出现的 R-xxx 编号均指仓库根 `README.md` 中的条款。

---

## 1. 本应用管什么

| 项 | 内容 |
|---|---|
| 应用 id | `tvbox` |
| 客户端 | TVBoxOSC 系（当前基线：`TVBOIX`） |
| 包清单 | `packages/包清单.csv` |
| 入口格式 | `api_index`（多线路索引） |
| 当前包 | `tvboxSL`（综合 / 少儿 / 长辈三条线路） |

---

## 2. 加载链路（源码可证）

| 编号 | 事实 | 依据 |
|---|---|---|
| A-TVB-01 | 配置地址先经 `configUrl()` 归一：`file://`→`clan://localhost/`；`clan` 前缀→`http://127.0.0.1:<端口>/file/`；其余非 http 前缀补 `http://` | `ApiConfig.java:170-192` |
| A-TVB-02 | 配置内容含 `"./` 或 `"../` 时执行 `fixContentPath()`，以**配置自身 URL** 为基准替换为绝对地址；先换 `../` 再换 `./` | `ApiConfig.java:1788-1798` |
| A-TVB-03 | 索引只认 `{"urls":[{"url","name"}]}`；内容含 `sites` 或无 `urls` 时不算索引 | `ApiConfig.java:671-703` |
| A-TVB-04 | 识别索引后自动加载第一条线路，并写入线路列表 | `ApiConfig.java:650-669` |
| A-TVB-05 | `type:3` 按 `api` 后缀分发加载器：`.js`→`JsLoader`；含 `.py`→`pyLoader`；其余→`JarLoader` | `ApiConfig.getCSP` |
| A-TVB-06 | 顶层 `spider` 由 OkHttp 下载，只接受 http(s)；本地场景依赖 `clanContentFix` 预处理 | `ApiConfig.java:438-458` |
| A-TVB-07 | jar 站点必须显式写 `sites[].jar`；否则回落到顶层 `spider`。**所有 jar 引用带 `;md5;`**（R-CFG-04） | `JarLoader.parseJar` |
| A-TVB-08 | `JsLoader` 以站点 `key` 缓存 spider 实例；不同 key 各自持有独立 JS 上下文，脚本内模块级变量互不串用 | `JsLoader.getSpider` |
| A-TVB-09 | JS 爬虫 `init(cfg)` 只保证拿到 `skey`/`stype`；`ext` 若为合法 JSON 会并入 `cfg` | `JsSpider.init` |
| A-TVB-10 | 客户端内置 `assets://js/lib/cat.js`，提供 `req`/`load`/`_` 等；脚本用 `import { req } from 'assets://js/lib/cat.js'` | 客户端 assets |

---

## 3. 入口写法

| 场景 | 写法 |
|---|---|
| 在线（GitHub/Gitee） | 直接填 `api_index.json` 的 raw 地址 |
| 本地安装 | 目录放 `/sdcard/TVBox/tvboxSL/`，配置地址填 `clan://localhost/tvboxSL/api_index.json` |
| 单线路调试 | 填该线路 `api.json` 的地址（此时不会出现「线路选择」，属预期） |

索引内线路地址必须按 4.3 节写成百分号编码的相对路径，例如 `./SL%20%E7%BB%BC%E5%90%88%E7%BA%BF%E8%B7%AF/api.json`。

---

## 4. 包内相对引用

| 对象 | 写法 | 说明 |
|---|---|---|
| 线路内脚本 | `./js/x.js`、`./py/x.py` | 相对当前线路目录 |
| 公共 jar | `../_common/jar/x.jar;md5;<32位>` | 相对当前线路目录的上一级 |
| 顶层 spider | `./spider_<代号>.jar;md5;<32位>` | 必须真实可加载 |

禁止：`file://`、`clan://`（仅本地入口由客户端自行转换，配置内不写）、`"./`/`"../` 出现在站点 `name`/`ext`/`flags` 中（R-NAM-16）。

---

## 5. 与仓库级文档的关系

- 新增包、改线路、改命名、改门禁 → 先改仓库根 `README.md`，再改本应用。
- 本文与仓库根冲突时，以仓库根为准（R-ARC-10）。
