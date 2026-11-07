# catmovie 应用导览（小猫影视）

单文件全量配置，客户端填一个地址即可加载。

## 入口

`https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/catmovie/config.json`

## 当前内容（1.1.0）

| 名称 | 上游 | 分类数 | 成人分类 |
|---|---|---|---|
| 极速｜猫眼影视 | `https://api.maoyanapi.top/api.php/provide/vod/` | 53 | 伦理片、里番动漫 |
| 极速｜爱坤影视 | `https://ikunzy.cc/api.php/provide/vod/` | 53 | 伦理片、里番动漫 |
| 快速｜360资源 | `https://360zy.com/api.php/provide/vod/` | 51 | 伦理片 |
| 快速｜量子资源 | `http://cj.lziapi.com/api.php/provide/vod/` | 40 | 伦理片 |
| 快速｜爱奇艺资源 | `https://iqiyizyapi.com/api.php/provide/vod/` | 43 | 里番动漫、伦理片 |
| 标准｜西瓜资源 | `https://xiguazy.tv/api.php/provide/vod/` | 43 | 伦理片 |
| 标准｜非凡资源 | `https://api.ffzyapi.com/api.php/provide/vod/` | 31 | 伦理片 |
| 标准｜天堂影视 | `https://caiji.dyttzyapi.com/api.php/provide/vod/` | 32 | 伦理片 |
| 标准｜龙马资源 | `http://jhysj.jiaheyy.top/api.php/provide/vod/` | 7 | 无 |

另含 1 条综合直播（VBSKY 综合）。

## 归类口径

- 分类按上游原样列出，顺序保持上游返回顺序。
- 成人分类不删除、不隐藏，只移至该源分类序列末尾，并在名称后加 `（成人）`。
- `extra.category` 以 JSON 字符串写入，值为 `[{"text":"分类名","id":"分类id"}]`。
- 不写 `nsfw`；成人按「源」分流，不按「分类」屏蔽。

## 与规范的关系

字段、命名、门禁、验收条款见 `规范/小猫影视源规范.md`；导入步骤见 `使用/小猫影视使用说明.md`。
