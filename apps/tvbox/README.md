# tvbox 应用导览

TVBoxOSC 系客户端的三线路影视源：综合 / 少儿 / 长辈，各线路站点数与版本见 `version.json`。主客户端为影视仓（CatVod 契约），TVBox 为兼容客户端。

## 入口（可直接复制）

地址由 `工具/发布/渲染.py` 从 `规则/平台地址.json` 生成，两平台并列；完整地址见 [发布/地址.md](../../发布/地址.md)：

<!-- 地址块开始：由 工具/发布/渲染.py 生成，勿手改 -->
| 场景 | 填到软件哪个入口 | GitHub 地址 | Gitee 地址 |
|---|---|---|---|
| 在线多线路 | 设置 → 配置地址（含线路切换） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_index.json` | `https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/tvbox/api_index.json` |
| 单文件全量 | 设置 → 配置地址（无线路切换） | `https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_all.json` | `https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/tvbox/api_all.json` |
| 本地整包 | 整包放 `/sdcard/TVBox/tvbox/` 后填 | `clan://localhost/tvbox/api_index_local.json` | 同 GitHub |

> Gitee 版索引：综合 → `api_all.json`（64 站，含少儿/长辈共 12 站重复）、少儿 → `kids/api.json`、长辈 → `elders/api.json`，三条地址互不相同，客户端可切换。单文件 `api_all.json` 是 64 站全量、没有线路切换。三条线路单独加载的地址见仓库根 [发布/地址.md](../../发布/地址.md)。
<!-- 地址块结束 -->

下表的仓库内路径在两平台一致：

| 场景 | 仓库内路径 / 填法 |
|---|---|
| 在线多线路 | `apps/tvbox/api_index.json` |
| 本地安装 | 整包放 `/sdcard/TVBox/tvbox/`，填 `clan://localhost/tvbox/api_index_local.json` |
| 单文件全量 | `apps/tvbox/api_all.json` |

填法与安装步骤见 `使用/TVBox 使用说明.md`；字段、命名、门禁、探活与验收条款见 `规范/TVBox 源规范.md`。

## 目录

| 路径 | 内容 |
|---|---|
| `api_index.json` / `api_index_local.json` / `api_all.json` | 三个入口，由 `工具/源生成/生成.py` 生成 |
| `api_index_rel.json` | 可搬迁入口：三条线路写成 `./std/api.json` 等相对地址，随目录上传到云盘后入口不必指回 GitHub/Gitee |
| `std/` `kids/` `elders/` | 三条线路，各自含 `api.json`、`spider.jar`、`js/` 等 |
| `_common/jar/` | 跨线路共用 jar |
| `version.json` | 版本与线路登记（客户端不读取） |
| `更新时间.txt` | 最后更新时间与本次改动一句话说明 |
| `目录说明.txt` | 随包分发的安装说明 |

三个配置入口均带顶层 `updateTime`（`YYYY-MM-DD HH:MM`），客户端读固定键、忽略多余键；索引同样带该键，仍只认 `urls`。

两个时间字段不要混用：`updateTime` = **站点数据时间**，只在站点增删或源规则改动导致数据变化时更新；`version.json` 的 `updated` = **版本发布时间**，每次发版更新。只改文档或只修索引而站点未变时，`updateTime` 保持不变。

名称标记：`🔎` 无分类页、直接搜索；`♻️` 可能失败、重试一次；`⚡/⏱/🐢` 为速度档。另有 5 条 py 与 13 条 ARM jar 属环境限制、未验证，不算源失效。

改内容的唯一入口是各线路 `api.json`；改完必须跑 `工具/源生成/生成.py`，不要手改三个入口文件。
