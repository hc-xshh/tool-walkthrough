"""插件 082：批次归档。

只在批处理里跑，单条导出不会走到这里。
"""

NAME = "plugin_082"
TOPIC = "批次归档"


def run(payload, context=None):
    """把 payload 里的字段原样透传，补一个处理标记。"""
    context = context or {}
    out = dict(payload or {})
    out["handled_by"] = NAME
    out["topic"] = TOPIC
    return out
