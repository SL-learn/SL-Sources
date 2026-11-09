# SL 自建源仓库

个人自用的多应用源仓库：TVBox（三条线路）、小猫影视（单文件全量）、阅读（书源与订阅源成品）。
仓库只收录可公开的配置、规则、模板、规范与工具。

## 有哪些应用

| 应用 | 入口 | 仓库内路径 |
|---|---|---|
| TVBox | `api_index.json`（多线路） | `apps/tvbox/api_index.json` |
| TVBox | `api_index_local.json`（本地整包） | `apps/tvbox/api_index_local.json`（填 `clan://localhost/tvbox/api_index_local.json`） |
| TVBox | `api_all.json`（单文件全量 64 站） | `apps/tvbox/api_all.json` |
| 小猫影视 | `config.json` | `apps/catmovie/config.json` |
| 阅读书源 | `书源.json`（111 条） | `apps/reading/书源.json` |
| 阅读订阅源 | `订阅源.json`（26 条） | `apps/reading/订阅源.json` |

## 可直接填写的地址（复制整行即可）

下表由 `工具/发布/渲染.py` 从 `规则/平台地址.json` 生成，GitHub 与 Gitee 并列；用哪个平台就抄哪一列。完整地址（含百分号编码、回滚旧版、加速）见 [地址.md](./地址.md)。**地址里不带版本号与日期，永久固定。**

<!-- 地址块开始：由 工具/发布/渲染.py 生成，勿手改 -->
| 应用 | 填到软件哪个入口 | GitHub 地址 | Gitee 地址 |
|---|---|---|---|
| TVBox / 影视仓 | 设置 → 配置地址（多仓索引，推荐，含线路切换） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_index.json` | `https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/tvbox/api_index.json` |
| TVBox / 影视仓 | 设置 → 配置地址（单文件全量 64 站，无线路切换） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_all.json` | `https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/tvbox/api_all.json` |
| TVBox / 影视仓 | 本地整包：整包放 `/sdcard/TVBox/tvbox/` 后填 | `clan://localhost/tvbox/api_index_local.json` | 同 GitHub |
| 小猫影视 | 设置 → 订阅配置（单文件） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/catmovie/config.json` | `https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/catmovie/config.json` |
| 阅读 | 书源管理 → 网络导入（书源 111 条） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/reading/书源.json` | 451 拦截，暂不可用 |
| 阅读 | 订阅 → 网络导入（订阅源 26 条） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/reading/订阅源.json` | 451 拦截，暂不可用 |

> 阅读的书源与订阅源是**两类分别导入**：先在「书源管理」填书源地址，再在「订阅」填订阅源地址。
> Gitee 的 `apps/tvbox/std/api.json`、`apps/reading/书源.json`、`apps/reading/订阅源.json` 被 451 拦截：TVBox 索引的综合线路改用 `api_all.json`（64 站），阅读改用 GitHub 地址。单文件 `api_all.json` 是 64 站全量、没有线路切换，需要综合/少儿/长辈切换请填 `api_index.json`。完整表格与百分号编码写法见 [地址.md](./地址.md)。
<!-- 地址块结束 -->

填法、安装步骤见 `使用/`；强制条款见 `规范/`。

## 双远端（GitHub 主源 + Gitee 国内镜像）

| 项 | GitHub | Gitee |
|---|---|---|
| 远端名 | `origin` | `gitee` |
| 角色 | 主源（支持 jsDelivr 加速） | 国内镜像，网络拉不动时改用 |
| 地址文件 | 本仓 `地址.md`（两平台地址并列，两侧内容一致） | 同路径 `地址.md`（同上） |

- 两平台地址**同源生成**：raw 基址只在 `规则/平台地址.json` 定义，`地址.md` 与各 README 的地址块都由渲染脚本写入，其余文档只写仓库内相对路径，禁止手写任一平台地址（`规范/仓库通用规范.md` 第 3.5 节）。
- 一条命令同步本地 `main` 与全部 tag 到两个远端：

  ```powershell
  powershell -ExecutionPolicy Bypass -File 工具\发布\同步双远端.ps1
  ```

  只推一个平台加 `-Only gitee`，演练加 `-DryRun`。详见 `工具/发布/说明.md`。

## 动手前必读顺序（任何新增源、改包都必须走这条链）

1. 读 `规范/`：先看 `规范/仓库通用规范.md`，再看对应应用的规范。
2. 跑 `工具/源检测/` 的 dry-run：只出报告，不改产物。
3. 需要修复时显式确认：`--apply` 才落盘，落盘前备份原文件。
4. 推送前过扫描门禁：只拦成人主体源文件、非公开内容、维护元数据与非公开词表；成人分类正文不阻断。
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
