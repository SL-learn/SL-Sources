# tvbox 应用导览

TVBoxOSC 系客户端（当前基线 `TVBOIX`）的三线路影视源：综合 123 站、少儿 17 站、长辈 11 站，合计 151 站。

## 入口

| 场景 | 地址 |
|---|---|
| 在线多线路 | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_index.json` |
| 本地安装 | 整包放 `/sdcard/TVBox/tvbox/`，填 `clan://localhost/tvbox/api_index_local.json` |
| 单文件全量 | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_all.json` |

填法与安装步骤见 `使用/TVBox 使用说明.md`；字段、命名、门禁、探活与验收条款见 `规范/TVBox 源规范.md`。

## 目录

| 路径 | 内容 |
|---|---|
| `api_index.json` / `api_index_local.json` / `api_all.json` | 三个入口，由 `工具/源生成/生成.py` 生成 |
| `std/` `kids/` `elders/` | 三条线路，各自含 `api.json`、`spider.jar`、`js/` 等 |
| `_common/jar/` | 跨线路共用 jar |
| `version.json` | 版本与线路登记（客户端不读取） |
| `目录说明.txt` | 随包分发的安装说明 |

改内容的唯一入口是各线路 `api.json`；改完必须跑 `工具/源生成/生成.py`，不要手改三个入口文件。
