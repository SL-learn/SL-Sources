# TVBox 使用说明

> 位置：`使用/TVBox 使用说明.md`｜读者：只想填地址看片的人。

> 不写内部判据；除第 8、9 章的分发条款（`TVB-DIST` 段）外，其余条款见 `规范/TVBox 源规范.md`。

## 8. 本地分发

| 编号 | 规则 |
|---|---|
| TVB-DIST-001 | 落地路径固定 `/sdcard/TVBox/<包id>/`；包目录名不得改（`tvbox`） |
| TVB-DIST-002 | 入口地址二选一：`clan://localhost/tvbox/api_index.json` 或 `file://tvbox/api_index.json` |
| TVB-DIST-003 | 整包拷贝必须包含 `_common/`、全部线路目录与 `api_index.json`；缺任一项即不可用 |
| TVB-DIST-004 | 迁移设备或换存储时整目录拷贝，不单独移动 jar；移动后入口地址不变 |
| TVB-DIST-005 | 本地形态与在线形态使用**同一份**文件，不得为本地单独改配置 |

**不满足的处理**：拷贝不完整、目录改名、为本地单独改配置，任一项命中则该次安装判失败。

---

## 9. 在线分发

### 9.1 托管取舍

| 渠道 | 角色 | 结论 |
|---|---|---|
| GitHub raw | 主源 | 采用；分支 `main`；支持 Range |
| Gitee raw | 国内镜像 | 采用；分支 `main`，与 GitHub 独立维护提交；`api_index.json`、`api_all.json` 按平台各自渲染，`地址.md` 两平台并列、两侧内容一致 |
| jsDelivr | 加速备选 | 仅 GitHub 侧提供，可用但不作主源：`@main` 缓存不可控 |
| 自选静态存放位置 | 仅便携版整包存放 | 不作仓库配置源；入口只写 `api_index_rel.json` 的直链 |

两平台的绝对地址不在本文档写死：仓库根 `地址.md` 两平台并列，根 `README.md` 与 `apps/tvbox/README.md` 的地址块可直接复制。**在线直填只认 GitHub 与 Gitee 两条仓库地址**，不把任何存放位置当配置源。

### 9.2 直链要求

| 编号 | 规则 |
|---|---|
| TVB-DIST-006 | 配置与 jar 的直链必须 200 或 302 到文件本体；不得是 HTML 落地页 |
| TVB-DIST-007 | 不得校验 Referer/Cookie；UA 必须容忍 `okhttp/3.15` |
| TVB-DIST-008 | 链接必须长期有效；带时效签名、需登录换取的链接不得作配置源 |
| TVB-DIST-009 | 在线入口指向 `api_index.json`；便携版入口指向 `api_index_rel.json`；包内引用保持相对路径，换存放位置不改包 |
| TVB-DIST-010 | 在线与本地共用同一份文件；在线更新只允许覆盖同路径文件（见第 10 章） |
| TVB-DIST-011 | GitHub 与 Gitee **分别发布、互不同步**：GitHub 推 `main` 与主 tag，Gitee 由本地 `gitee` 分支重建树后渲染并推 `gitee:main`；除按平台渲染的两个入口产物（`apps/tvbox/api_index.json`、`apps/tvbox/api_all.json`）外，其余文件（含 `地址.md` 与各 README 地址块）两平台必须字节一致（SYS-DIST-003） |

### 9.3 自选静态存放位置直链判定（仅用于便携版，不作仓库配置源）

| 项 | 做法 | 通过判据 |
|---|---|---|
| ① 直链性 | `curl -I <直链>` | 200/206，`Content-Type` 为 json/jar/octet-stream，非 `text/html` |
| ② 免鉴权 | 去掉 Referer、Cookie，改用 `okhttp/3.15` 重试 | 仍 200/206 |
| ③ 稳定性 | 生成链接 24 小时后再测 | 仍可用，无签名过期 |
| ④ 限速 | 连续下载 12 MB 公共 jar | 平均 ≥200 KB/s，无强制断流 |

任一项不通过：该存放位置仅作整包下载/备份，不写进任何 `api.json` 或入口地址。

### 9.4 便携版（相对索引）

- [ ] 整包上传到自选静态存放位置后，入口填 `<存放位置>/tvbox/api_index_rel.json`；该文件内三条 url 均为 `./std/api.json` 等相对写法。
- [ ] 索引与其指向的线路文件必须保持同一目录结构，且路径全 ASCII；否则相对解析会失败（历史坑：中文目录百分号编码）。
- [ ] 索引及线路内部不得出现本仓 GitHub/Gitee 地址；`jar` 字段必须相对。导出时由脚本重写并扫描，命中即失败。
- [ ] 本地使用兜底：填 `clan://localhost/tvbox/api_index_rel.json`。

**不满足的处理**：TVB-DIST-006/TVB-DIST-007/TVB-DIST-008 违反 → 该渠道停用；TVB-DIST-011 不一致 → 当次发布作废。

---

## 10. 源名称标记怎么看

| 标记 | 含义 |
|---|---|
| `🔎` | 该源没有分类页，请到搜索框直接搜索片名使用 |
| `♻️` | 该源可能失败，失败时重试一次或换个词再搜 |
| `⚡` / `⏱` / `🐢` | 响应速度：快 / 一般 / 慢 |

一句话记法：**带 🔎 的源没有分类页，直接搜索用。**

另有 5 条 py 源与 13 条 ARM jar 源未收录：前者需客户端带 Python 引擎，后者需 ARM 设备才能加载其 `.so`，**属环境限制、尚未验证，不等于源失效**；换 ARM 设备或对应客户端包后可再验。

---
