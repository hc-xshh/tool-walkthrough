"""幂等键。

客户端为每次「逻辑请求」生成一个 request_id；重试沿用同一个 id。
"""


def build_key(request, now=None):
    """返回这次扣款在幂等存储里的键：就是客户端给的 request_id。"""
    return request.request_id
