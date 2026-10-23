"""插件 044：渠道映射。

不参与 CSV 导出，只在报表流水线上做字段补全。
"""

NAME = "plugin_044"
TOPIC = "渠道映射"


def run(payload, context=None):
    """把 payload 里的字段原样透传，补一个处理标记。"""
    context = context or {}
    out = dict(payload or {})
    out["handled_by"] = NAME
    out["topic"] = TOPIC
    return out
