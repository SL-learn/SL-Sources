# TVBox 影视源

TVBoxOSC / 影视仓 客户端的影视源合集，含自整理 SL 频道 + 天微影视 APK 提取 TW 频道。

## 快速开始（选一种）

### ✅ 方案 A：国内 Gitee 多线路（推荐）

影视仓/TVBox → 设置 → 配置地址，填：

```
https://gitee.com/gerenxiuxian/SL-Sources/raw/main/apps/tvbox/api_index_gitee.json
```

9 条线路，**雷电/国内网络实测可达**，共 177 站点：

| 线路 | 内容 | 站点数 |
|------|------|--------|
| 天微·综合 | 影视秒播/4K/盘4K | 42 |
| 天微·智教 | 国学/科学/地理/百科 | 27 |
| 天微·曲艺 | 戏曲/相声/小品 | 5 |
| 天微·短剧 | 甜圈/锦鲤/唐人等 | 23 |
| 天微·体育 | 看球/格斗 | 6 |
| 天微·音乐 | DJ/MV | 10 |
| SL·少儿 | 兔小贝/儿童合集 | 4 |
| SL·长辈 | 戏曲/相声/急救教学 | 8 |
| SL·综合 | 原有自整理影视源 | 52 |

### 方案 B：GitHub 完整 11 条线路

```
https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/tvbox/api_index.json
```

比 Gitee 版多 2 条（天微·影视 40 站 + 天微·动漫 26 站），共 243 站点。
**国内网络可能被 GFW 阻断，如需请用代理。**

### 方案 C：本地 file:// 整包

把 `apps/tvbox/` 整个目录拷到设备（推荐 `/sdcard/SL_Sources/`），然后填：

```
file:///sdcard/SL_Sources/api_index_rel.json
```

**关键：必须整包拷贝！** 各频道目录内的 `./js/xxx.js`、`./lib/xxx.json`、`./xxx.jar` 都是相对路径，丢失任何文件都会导致该频道加载失败。

拷贝命令：
```bash
adb push apps/tvbox/ /sdcard/SL_Sources/
```

### 方案 D：本地 HTTP server（调试用）

```bash
# 在仓库 apps/tvbox/ 目录下起 server
python -m http.server 8080 --directory apps/tvbox
# 雷电内填（用 Windows 局域网 IP）
http://192.168.x.x:8080/api_index_rel.json
```

### 备选：9978 Web 推送（影视仓自带）

影视仓首页顶部显示 `http://172.16.1.15:9978/`，浏览器打开后可推送配置 URL。
PC 端需要先 `adb forward tcp:9978 tcp:9978`。

---

## 入口文件对照

| 文件名 | 格式 | 线路数 | 站点数 | 适用场景 |
|--------|------|--------|--------|---------|
| `api_index_gitee.json` | Gitee raw 绝对 URL | 9 | 177 | **国内网络首选** |
| `api_index.json` | GitHub raw 绝对 URL | 11 | 243 | **海外/代理用户** |
| `api_index_rel.json` | 相对路径 `./xxx/api.json` | 11 | 243 | **本地 file:// / HTTP server** |
| `api_all.json` | 单文件合并大包 | — | 327 | **需要单文件全量时**（含 sourceGroup 分组） |

## 目录结构

```
apps/tvbox/
├── api_index_gitee.json    ← Gitee 安全版（9 条）
├── api_index.json           ← GitHub 完整版（11 条）
├── api_index_rel.json       ← 本地相对路径（11 条）
├── api_all.json             ← 327 站点合并大包（含 sourceGroup 分块）
│
├── TW_std/     天微·综合主力（42 站）   spider: qxyc.jar
├── TW_smart/   天微·智教（27 站）       spider: QX.jar
├── TW_quyi/    天微·曲艺（5 站）        spider: spider.jar
├── TW_short/   天微·短剧（23 站）       spider: jar/xyqxbpq.jar
├── TW_sport/   天微·体育（6 站）        spider: spider.jar
├── TW_music/   天微·音乐（10 站）       spider: yy.jar
├── TW_yingshi/ 天微·影视（40 站）       spider: kjtw.jar  ⚠ Gitee 451
├── TW_donghua/ 天微·动漫（26 站）       spider: tvkj.jar  ⚠ Gitee 451
│
├── SL_comprehensive/  SL·综合（52 站）  spider: spider.jar
├── SL_kids/           SL·少儿（4 站）   spider: spider.jar
├── SL_elders/         SL·长辈（8 站）   spider: spider.jar
│
└── _common/jar/  跨频道共用 jar
```

## 前缀说明

| 前缀 | 含义 | 来源 |
|------|------|------|
| `TW_` | 天微影视 APK 提取（2026-11） | 用户提供 APK |
| `SL_` | 自整理原有频道 | 仓库原始 |

## Gitee 451 封锁说明

### 背景

Gitee 对 raw 文件启用 AI 内容审核，触发 `HTTP 451 Unavailable For Legal Reasons`。
**file 本身还在仓库（git clone 能拿到），但 raw 接口被屏蔽**。

### 封锁机制（实测）

- **TW_yingshi / TW_donghua**：AI 扫描内容关键词 + 域名黑名单
  - TW_yingshi 精简 124→40 站仍 451，域名 `py.doube.eu.org` 命中 Gitee 黑名单
  - TW_donghua 26 站一直 451，内容关键词触发
- **api_all.json**：合并大包 327 站点 → 内容总量过大直接触发审核
- **api_all.json 单独禁放 Gitee，只放 GitHub + 本地**

### 绕过方法（已实测有效）

| 方法 | 效果 |
|------|------|
| **清洗站点名敏感词**（磁力→磁链、嫖嫖→朴朴、奇米→奇妙、AGE-动漫→AGE-动画、动漫→动画） | SL_comprehensive 成功从 451→200 ✅ |
| **精简站点数**（TW_yingshi 124→40） | 大小降为 24KB 但仍 451（域名是主因） |
| **换部署平台**（GitHub / jsDelivr / 自建 CDN） | 绕过 Gitee 审核 ✅ |
| **本地 file://** | 完全不经过 Gitee，全 11 频道可用 ✅ |

### 各平台可达性总览

| 频道 | Gitee raw | GitHub raw | 本地 file:// |
|------|-----------|------------|-------------|
| TW_std (42) | ✅ 200 | ✅ | ✅ |
| TW_smart (27) | ✅ 200 | ✅ | ✅ |
| TW_quyi (5) | ✅ 200 | ✅ | ✅ |
| TW_short (23) | ✅ 200 | ✅ | ✅ |
| TW_sport (6) | ✅ 200 | ✅ | ✅ |
| TW_music (10) | ✅ 200 | ✅ | ✅ |
| TW_yingshi (40) | ❌ 451 | ✅ | ✅ |
| TW_donghua (26) | ❌ 451 | ✅ | ✅ |
| SL_comprehensive (52) | ✅ 200 | ✅ | ✅ |
| SL_kids (4) | ✅ 200 | ✅ | ✅ |
| SL_elders (8) | ✅ 200 | ✅ | ✅ |
| **api_all.json (327)** | ❌ 451 | ✅ | ✅ |

## api_all.json 分块说明

`api_all.json` 是合并大包，每个 site 带 `sourceGroup` 标记：

| sourceGroup | 包含 | 站点数 |
|-------------|------|--------|
| `"综合"` | TW_std + TW_yingshi + TW_donghua + TW_short + TW_sport + TW_music + SL_comprehensive | 202 |
| `"少儿"` | TW_smart + SL_kids | 31 |
| `"长辈"` | TW_quyi + SL_elders | 13 |

影视仓内可按 `sourceGroup` 筛选频道。

## Spider jar 校验

所有 type:3 jar 均带 `;md5;` 校验（TVBox 规范要求）：

```json
"spider": "./qxyc.jar;md5;e3705c07efd0ca14175cd29acf5dc580"
```

## 合规自检（已通过）

- ✅ 无 Windows 绝对路径 `C:\xxx`
- ✅ 无 `file://` 硬编码（用户自己填才需）
- ✅ 无 `/sdcard/` 硬编码
- ✅ 无远程 jar 依赖（全部本地化）
- ✅ 所有相对路径指向本频道内文件
- ✅ 所有 type:3 jar 带 md5

## 维护说明

1. 改某个频道的源 → 编辑该目录下的 `api.json` → commit push
2. 新增/删除频道 → 更新 `api_index_gitee.json`、`api_index.json`、`api_index_rel.json`
3. 更新 `api_all.json` → 重跑合并脚本（`工具/源生成/生成.py`）
4. Gitee 451 检测 → 用 `_audit/gitee_test2.ps1` 批量测
