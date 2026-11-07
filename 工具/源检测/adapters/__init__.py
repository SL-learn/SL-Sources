"""应用适配器注册表。

新增应用只需在此登记模块名与类名，并在 rules/<应用>.json 写检查/修复参数。
"""

from __future__ import annotations


_APPS = {
    "阅读": ("reading", "ReadingAdapter", "阅读"),
    "阅读-订阅源": ("rss", "RssAdapter", "阅读-订阅源"),
    "订阅源": ("rss", "RssAdapter", "阅读-订阅源"),
    "TVBox": ("tvbox", "TVBoxAdapter", "TVBox"),
    "小猫": ("catmovie", "CatmovieAdapter", "小猫影视"),
    "小猫影视": ("catmovie", "CatmovieAdapter", "小猫影视"),
}

APP_NAMES = ["阅读", "阅读-订阅源", "TVBox", "小猫影视"]


def resolve_app(app: str) -> tuple[str, str, str]:
    """返回 (模块名, 类名, 规则文件基名)。"""
    if app in _APPS:
        return _APPS[app]
    raise ValueError(f"未知应用：{app}（可选：{'、'.join(APP_NAMES)}）")


def create_adapter(app: str, rules: dict, domain: str = ""):
    module_name, class_name, _rule_name = resolve_app(app)
    module = __import__(f"adapters.{module_name}", fromlist=[class_name])
    cls = getattr(module, class_name)
    return cls(rules, domain)
