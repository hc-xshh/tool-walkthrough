"""插件 029：税率计算。

保留给旧版导出器调用，新代码不要依赖。
"""

NAME = "plugin_029"
TOPIC = "税率计算"


def run(payload, context=None):
    """把 payload 里的字段原样透传，补一个处理标记。"""
    context = context or {}
    out = dict(payload or {})
    out["handled_by"] = NAME
    out["topic"] = TOPIC
    return out
