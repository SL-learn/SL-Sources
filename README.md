# SL 自建源仓库

个人自用的多应用源仓库：TVBox（三条线路）、小猫影视（单文件全量）、阅读（书源与订阅源成品）。
仓库只收录可公开的配置、规则、模板、规范与工具。

## 有哪些应用

| 应用 | 入口 | 在线地址 |
|---|---|---|
| TVBox | `api_index.json`（多线路） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_index.json` |
| TVBox | `api_index_local.json`（本地） | `clan://localhost/tvbox/api_index_local.json` |
| TVBox | `api_all.json`（单文件全量 65 站） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_all.json` |
| 小猫影视 | `config.json` | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/catmovie/config.json` |
| 阅读书源 | `书源.json`（111 条） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/reading/%E4%B9%A6%E6%BA%90.json` |
| 阅读订阅源 | `订阅源.json`（26 条） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/reading/%E8%AE%A2%E9%98%85%E6%BA%90.json` |

填法、安装步骤见 `使用/`；强制条款见 `规范/`。**地址里不带版本号与日期，永久固定。**

## 动手前必读顺序（任何新增源、改包都必须走这条链）

1. 读 `规范/`：先看 `规范/仓库通用规范.md`，再看对应应用的规范。
2. 跑 `工具/源检测/` 的 dry-run：只出报告，不改产物。
3. 需要修复时显式确认：`--apply` 才落盘，落盘前备份原文件。
4. 推送前过扫描门禁：只拦成人主体源文件、私有域内容、维护元数据与私有词表；成人分类正文不阻断。
5. 追加 `变更/CHANGELOG-<应用>.md` 与 `记录/版本对照表.csv`，再发版打 tag。

不允许绕开这条链直接改产物。

## 目录导览

| 目录 | 放什么 |
|---|---|
| `apps/` | 各应用发布物：`tvbox/`、`catmovie/`、`reading/` |
| `规范/` | 人读强制条款（编号化，`<应用>-<类别>-<序号>`） |
| `使用/` | 客户端怎么填地址、怎么装、怎么切线路 |
| `规则/` | 机读判据与阈值，检测/生成工具直接读取 |
| `工具/` | `源生成/`、`源检测/`，各带 `说明.md` |
| `变更/` | 只追加的 CHANGELOG |
| `记录/` | 逐次检测报告、探活、体检表、版本对照表 |

完整的文档职责表见 [文档索引.md](./文档索引.md)。

## 版本与发布

- 仓库整体版本用 tag `repo-v<主>.<次>.<修订>`；各应用版本用 tag `<应用id>-v<主>.<次>.<修订>`，并写进各自 `version.json`。
- 版本号只存在于 `version.json` 与 Git tag，**不进任何对外路径或文件名**。
- 发版后必须追加 `记录/版本对照表.csv`，旧行不改写。

细则见 `规范/仓库通用规范.md` 第 10 章。

## 免责声明

本仓库只做配置聚合与工具，不存储、不转存任何影视或文学内容；所有内容版权归原站点所有。
如有侵权，请通知仓库所有者，收到通知后立即移除对应条目。完整声明见 [声明.md](./声明.md)。
