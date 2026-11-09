# SL-Sources 公开源仓

> 文档编号：D01｜性质：本仓入口｜基线：2026-11-09｜本仓只收录公开源，私有源的判定证据与成人内容不在本仓。

## 1. 这是什么

三个应用，每个应用一个目录，按客户端直接可用的成品文件组织：

| 应用 | 成品 | 客户端 |
|---|---|---|
| TVBox / 影视仓 | `apps/tvbox/` 多线路索引与全量单文件 | 影视仓（CatVod 契约）为主，TVBox 兼容 |
| 小猫影视 | `apps/catmovie/config.json` | 小猫影视 |
| 阅读 | `apps/reading/书源.json`、`apps/reading/订阅源.json` | Legado / 阅读 3.x |

路径冻结：入口文件名与目录名不带版本号、日期；改版只改内容，已发布地址不失效。

## 2. 文档地图（D01–D11）

| 编号 | 路径 | 只放什么 |
|---|---|---|
| D01 | `README.md` | 本文件：是什么、目录地图、维护链 |
| D02 | `使用/` | 三个客户端怎么填地址、怎么导入 |
| D03 | `规范/` | 强制条款正本（按应用分册） |
| D04 | `变更/` | 各应用 CHANGELOG 与映射表 |
| D05 | `记录/README.md` | 只有版本事实指针：过程数据不进公开仓 |
| D06 | `文档索引.md` | 文档地图，≤30 行 |
| D07 | `清单/` | 应用清单、包清单、版本对照表（CSV） |
| D08 | `决策记录.md` | 拍板记录（只追加） |
| D09 | `声明.md` | 合规与免责 |
| D10 | `发布/` | 发布说明、构建说明、双平台地址 |
| D11 | `工具/` | 脚本指针与运行命令（脚本本体在仓外工作区，不入库） |

## 3. 直接使用

<!-- 地址块开始：由 工具/发布/渲染.py 生成，勿手改 -->
| 应用 | 填到软件哪个入口 | GitHub 地址 | Gitee 地址 |
|---|---|---|---|
| TVBox / 影视仓 | 设置 → 配置地址（多仓索引，推荐，含线路切换） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_index.json` | `https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/tvbox/api_index.json` |
| TVBox / 影视仓 | 设置 → 配置地址（单文件全量 64 站，无线路切换） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_all.json` | `https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/tvbox/api_all.json` |
| TVBox / 影视仓 | 本地整包：整包放 `/sdcard/TVBox/tvbox/` 后填 | `clan://localhost/tvbox/api_index_local.json` | 同 GitHub |
| 小猫影视 | 设置 → 订阅配置（单文件） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/catmovie/config.json` | `https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/catmovie/config.json` |
| 阅读 | 书源管理 → 网络导入（书源 100 条） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/reading/书源.json` | 451 拦截，暂不可用 |
| 阅读 | 订阅 → 网络导入（订阅源 22 条） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/reading/订阅源.json` | 451 拦截，暂不可用 |

> 阅读的书源与订阅源是**两类分别导入**：先在「书源管理」填书源地址，再在「订阅」填订阅源地址。
> Gitee 的 `apps/tvbox/std/api.json`、`apps/reading/书源.json`、`apps/reading/订阅源.json` 被 451 拦截：TVBox 索引的综合线路改用 `api_all.json`（64 站），阅读改用 GitHub 地址。单文件 `api_all.json` 是 64 站全量、没有线路切换，需要综合/少儿/长辈切换请填 `api_index.json`。完整表格与百分号编码写法见 [发布/地址.md](发布/地址.md)。
<!-- 地址块结束 -->

完整表格、百分号编码写法与 tag 固定地址见 [发布/地址.md](发布/地址.md)。

## 4. 事实来源（不手抄数字）

版本号、条数、更新时间**只写在两处**：

- `apps/<应用>/version.json`：本应用当前版本与条数；
- `清单/`：跨应用台账（`应用清单.csv`、`包清单-*.csv`、`版本对照表.csv`）。

README、发布说明、CHANGELOG、文档索引只引用上述位置，不再抄写具体数字。门禁与一致性校验按 `规范/仓库通用规范.md` 第 10 章（SYS-VER-002）执行；历次版本号与条数漂移的根因就是四处手抄，证据见 [决策记录.md](决策记录.md)。

公开仓**只留成果与规则**。观察池、探活/体检报告、测试日志、截图、中间导出、草稿等过程数据一律不入库；原件在工作区 `SL_TVBOX/归档/公开仓过程数据/`，逐条登记与回滚方式见 [归档/索引.csv](归档/索引.csv)（SYS-DOC-004）。

## 5. 维护链

```text
改 apps/tvbox/<线路>/api.json（唯一事实来源）
  → 生成.py --check → 生成.py（多线路索引 / 全量单文件）
  → 校验.py（本地视角）
  → 渲染.py --check --platform github|gitee（地址与多线路唯一性门禁）
  → 发布.ps1（GitHub main / Gitee gitee:main）
  → 升版本 + 变更/CHANGELOG-<应用>.md + 清单/版本对照表.csv + tag
```

命令与参数见 [工具/README.md](工具/README.md)；双平台机制见 [发布/构建说明.md](发布/构建说明.md)。

## 6. 双远端

| 项 | GitHub | Gitee |
|---|---|---|
| 远端名 | `origin` | `gitee` |
| 角色 | 主源（支持 jsDelivr 加速） | 国内镜像 |
| 分支 | `main` | `main`（由本地 `gitee` 分支整树重建） |
| 平台差异 | 仅 `apps/tvbox/api_index.json`、`api_all.json` | 同上 |

两平台内容除索引指向外逐字节一致；不接受手工推送，统一走 `发布.ps1`。
