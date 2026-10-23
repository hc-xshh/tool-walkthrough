"""插件 091：退款对账。

历史遗留：字段名是拼音缩写，别按字面理解。
"""

NAME = "plugin_091"
TOPIC = "退款对账"


def run(payload, context=None):
    """把 payload 里的字段原样透传，补一个处理标记。"""
    context = context or {}
    out = dict(payload or {})
    out["handled_by"] = NAME
    out["topic"] = TOPIC
    return out
