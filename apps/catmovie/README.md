# catmovie 应用导览（小猫影视）

单文件全量配置，客户端填一个地址即可加载。

## 入口

`https://raw.githubusercontent.com/SL-learn/SL-Sources/main/apps/catmovie/config.json`

## 当前内容（1.2.0）

公开点播源 36 条（极速 6、快速 6、慢速 3、间歇 21），直播源 6 条。按档位排序，慢速与间歇不剔除。

| 名称 | 上游 | 分类数 | 成人分类 |
|---|---|---|---|
| 极速｜360资源（360zyzz） | `https://360zyzz.com/api.php/provide/vod/` | 51 | 1 |
| 极速｜360资源（360zy） | `https://360zy.com/api.php/provide/vod/` | 51 | 1 |
| 极速｜ikun资源 | `https://ikunzy.cc/api.php/provide/vod/` | 53 | 2 |
| 极速｜猫眼影视 | `https://api.maoyanapi.top/api.php/provide/vod/` | 53 | 2 |
| 极速｜西瓜资源 | `https://xiguazy.tv/api.php/provide/vod/` | 43 | 1 |
| 极速｜量子资源 | `http://cj.lziapi.com/api.php/provide/vod/` | 40 | 1 |
| 快速｜天堂资源 | `https://caiji.dyttzyapi.com/api.php/provide/vod/` | 32 | 1 |
| 快速｜暴风资源 | `https://bfzyapi.com/api.php/provide/vod/` | 49 | 1 |
| 快速｜火狐资源 | `https://hhzyapi.com/api.php/provide/vod/` | 48 | 1 |
| 快速｜爱奇艺资源 | `https://iqiyizyapi.com/api.php/provide/vod/` | 43 | 2 |
| 快速｜非凡资源 | `https://api.ffzyapi.com/api.php/provide/vod/` | 31 | 1 |
| 快速｜龙马资源 | `http://jhysj.jiaheyy.top/api.php/provide/vod/` | 7 | 0 |
| 慢速｜如意资源 | `https://www.ryzyw.com/api.php/provide/vod/` | 43 | 1 |
| 慢速｜速播资源 | `https://subocaiji.com/api.php/provide/vod/` | 44 | 1 |
| 慢速｜金鹰资源 | `https://jyzyapi.com/api.php/provide/vod/` | 44 | 1 |
| 间歇｜U酷资源 | `https://api.ukuapi88.com/api.php/provide/vod/` | 29 | 1 |
| 间歇｜乐播资源 | `https://lbapi9.com/api.php/provide/vod/` | 17 | 4 |
| 间歇｜光速资源 | `https://api.guangsuapi.com/api.php/provide/vod/` | — | — |
| 间歇｜大众影视 | `https://cdn.dzzyapi.com/api.php/provide/vod/` | 32 | 1 |
| 间歇｜天涯影视 | `https://tyyszy.com/api.php/provide/vod/` | 39 | 1 |
| 间歇｜快车资源(快) | `https://caiji.kuaichezy.org/api.php/provide/vod/` | 59 | 6 |
| 间歇｜新浪资源 | `https://api.xinlangapi.com/xinlangapi.php/provide/vod/` | — | — |
| 间歇｜无尽资源 | `https://api.wujinapi.com/api.php/provide/vod/` | 63 | 6 |
| 间歇｜无水印资源 | `https://api.wsyzy.net/api.php/provide/vod/` | 60 | 6 |
| 间歇｜最大资源 | `https://api.zuidapi.com/api.php/provide/vod/` | 59 | 6 |
| 间歇｜极速资源 | `https://jszyapi.com/api.php/provide/vod/` | 48 | 1 |
| 间歇｜樱花资源 | `https://m3u8.apiyhzy.com/api.php/provide/vod/` | — | — |
| 间歇｜百度资源 | `https://api.apibdzy.com/api.php/provide/vod/` | — | — |
| 间歇｜红牛资源 | `https://www.hongniuzy2.com/api.php/provide/vod/` | 44 | 1 |
| 间歇｜艾旦影视 | `https://www.lovedan.net/api.php/provide/vod/` | 70 | 7 |
| 间歇｜虎牙资源 | `https://www.huyaapi.com/api.php/provide/vod/` | 44 | 1 |
| 间歇｜金鹰点播 | `https://jinyingzy.com/api.php/provide/vod/` | 44 | 1 |
| 间歇｜闪电资源(xsd) | `https://xsd.sdzyapi.com/api.php/provide/vod/` | 59 | 6 |
| 间歇｜飘零影视 | `https://p2100.net/api.php/provide/vod/` | 27 | 0 |
| 间歇｜魔都资源 | `https://www.mdzyapi.com/api.php/provide/vod/` | 42 | 2 |
| 间歇｜鸭鸭资源 | `https://cj.yayazy.net/api.php/provide/vod/` | 59 | 6 |

「—」表示分类表在探活时未取到，客户端会按上游原生分类展示，不写 `extra.category`。直播源：央视 1、卫视 1、综合 2、体育 1、地方 1。

## 归类口径

- 分类按上游原样列出，顺序保持上游返回顺序。
- 成人分类不删除、不隐藏，只移至该源分类序列末尾，并在名称后加 `（成人）`。
- `extra.category` 以 JSON 字符串写入，值为 `[{"text":"分类名","id":"分类id"}]`。
- 不写 `nsfw`；成人按「源」分流：成人主体源单独存放，不进入本文件。

## 与规范的关系

字段、命名、门禁、验收条款见 `规范/小猫影视源规范.md`；导入步骤见 `使用/小猫影视使用说明.md`。
