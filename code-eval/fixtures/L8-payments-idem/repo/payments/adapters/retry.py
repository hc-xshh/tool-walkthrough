"""重试工具（给渠道适配器用，不参与主扣款流程）。"""

import time


def with_retry(fn, attempts=3, backoff=0.1):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # 渠道侧异常，重试
            last = exc
            time.sleep(backoff * (i + 1))
    raise last
