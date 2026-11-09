# 发布

> 文档编号：D10｜性质：发布入口｜机制细节见 `构建说明.md`，脚本命令见 `../工具/README.md`

## 1. 发布物

| 文件 | 作用 | 谁在用 |
|---|---|---|
| `地址.md` | 两平台地址并列（渲染产物，勿手改） | 用户填地址 |
| `地址模板.md` | 地址文档模板，`{{GITHUB_RAW}}` / `{{GITEE_RAW}}` 占位 | 渲染脚本 |
| `构建说明.md` | 渲染、推送、导出便携版的机制与门禁 | 维护者 |

便携包（目录与 zip）导出到 `发布/云端/TVBox-便携版-<版本>/`，**不入库**（`.gitignore` 已排除）。

## 2. 双远端

| 项 | GitHub | Gitee |
|---|---|---|
| 远端名 | `origin` | `gitee` |
| 分支 | `main` | `main`（本地 `gitee` 分支整树重建后推送） |
| 角色 | 主源 | 国内镜像 |
| 平台差异 | 仅 `apps/tvbox/api_index.json`、`apps/tvbox/api_all.json` | 同上 |

不接受手工推送；统一走 `工具/发布/发布.ps1`。禁止 force、禁止改写历史、禁止移动旧 tag。

## 3. tag

| 类型 | 形式 | 只进 |
|---|---|---|
| 应用版本 | `<应用id>-v<版本>` | GitHub |
| Gitee 平台 | `<应用id>-v<版本>-gitee` | Gitee |
| 仓库整体 | `repo-v<版本>` | GitHub |
| 检查点 | `p<阶段>-<序号>` | 两侧本地与各自远端 |

版本号唯一来源是 `apps/<应用>/version.json`；tag 必须与它一致。

## 4. 发版顺序

```text
改源 → 生成.py --check → 生成.py → 校验.py
     → 渲染.py --check --platform github|gitee
     → 升版本（version.json + 清单/版本对照表.csv）
     → 追加 变更/CHANGELOG-<应用>.md
     → 发布.ps1 [-Tag]
```

各应用历史见 `../变更/CHANGELOG-<应用>.md`；本次发布摘要见该文件最新一行，不再另写发布说明。
