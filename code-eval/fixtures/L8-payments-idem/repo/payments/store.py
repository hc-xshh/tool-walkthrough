"""幂等存储：键 -> (存入时间, 结果)，按 TTL 过期。"""


class IdempotencyStore:
    def __init__(self, ttl_seconds=86400):
        self.ttl_seconds = ttl_seconds
        self._data = {}

    def get(self, key, now):
        record = self._data.get(key)
        if record is None:
            return None
        stored_at, result = record
        if now - stored_at > self.ttl_seconds:
            return None
        return result

    def put(self, key, result, now):
        self._data[key] = (now, result)

    def __len__(self):
        return len(self._data)
