"""把一批增量变更合进本地账本。

feed 形状：
    {"batch_id": "b-1", "changes": [
        {"op": "upsert", "note": {"id": "n1", "title": "…", "updated_at": "2026-03-01T10:00:00+00:00", "revision": 1}},
        {"op": "delete", "id": "n2", "updated_at": "2026-03-02T10:00:00+00:00"}
    ]}

规则：
- upsert 比较 (updated_at, revision)，严格更新才覆盖；
- delete 删除本地记录，并把删除时间写进 tombstones；
- 已删除的 id 收到不晚于墓碑的 upsert 时跳过（不复活）；
- 整批先校验，任何一条不合法都不改动输入。
"""

from datetime import datetime


def _parse_ts(value, field):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} 必须是非空 ISO 时间字符串")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 不是合法 ISO 时间: {value!r}") from exc


def _note_key(note):
    return (note["updated_at"], int(note.get("revision", 0)))


def _validate(change):
    if not isinstance(change, dict):
        raise ValueError("change 必须是对象")
    op = change.get("op")
    if op == "upsert":
        note = change.get("note")
        if not isinstance(note, dict) or not str(note.get("id") or "").strip():
            raise ValueError("upsert 缺少 note.id")
        _parse_ts(note.get("updated_at"), "note.updated_at")
        revision = note.get("revision", 0)
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise ValueError("note.revision 必须是整数")
        return
    if op == "delete":
        if not str(change.get("id") or "").strip():
            raise ValueError("delete 缺少 id")
        _parse_ts(change.get("updated_at"), "delete.updated_at")
        return
    raise ValueError(f"未知的 op: {op!r}")


def apply_batch(notes, tombstones, batch):
    """返回 (notes, tombstones, stats)。"""
    changes = batch.get("changes")
    if not isinstance(changes, list):
        raise ValueError("batch.changes 必须是数组")
    for change in changes:
        _validate(change)

    index = {n["id"]: n for n in notes}
    tombs = dict(tombstones)
    applied = skipped = deleted = 0

    for change in changes:
        if change["op"] == "upsert":
            note = dict(change["note"])
            nid = note["id"]
            if nid in tombs and note["updated_at"] <= tombs[nid]:
                skipped += 1
                continue
            local = index.get(nid)
            if local is not None and _note_key(note) <= _note_key(local):
                skipped += 1
                continue
            index[nid] = note
            tombs.pop(nid, None)
            applied += 1
        else:
            nid = change["id"]
            ts = change["updated_at"]
            if nid in index:
                del index[nid]
                deleted += 1
            else:
                skipped += 1
            if ts > tombs.get(nid, ""):
                tombs[nid] = ts

    return (
        list(index.values()),
        tombs,
        {"applied": applied, "skipped": skipped, "deleted": deleted},
    )
