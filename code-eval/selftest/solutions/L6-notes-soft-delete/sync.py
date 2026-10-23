"""把一批增量变更合进本地账本（第二轮：软删除）。

规则：
- delete 不再移除记录，而是写 deleted_at（删除时间）；tombstones 只用于迁移；
- 已软删的记录，updated_at 严格晚于 deleted_at 的 upsert 才复活；
- 旧 tombstones 里的删除时间在第一次同步时落到 deleted_at，随后清空；
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
    """返回 (notes, tombstones, stats)。软删除后 notes 里保留记录，只是带 deleted_at。"""
    changes = batch.get("changes")
    if not isinstance(changes, list):
        raise ValueError("batch.changes 必须是数组")
    for change in changes:
        _validate(change)

    index = {n["id"]: dict(n) for n in notes}
    applied = skipped = deleted = 0

    # 迁移：旧墓碑的删除时间落到 deleted_at，然后清空墓碑
    for nid, ts in list(tombstones.items()):
        local = index.get(nid)
        if local is not None and not local.get("deleted_at"):
            local["deleted_at"] = ts
    tombs = {}

    for change in changes:
        if change["op"] == "upsert":
            note = dict(change["note"])
            nid = note["id"]
            note.pop("deleted_at", None)
            local = index.get(nid)
            if local is None:
                index[nid] = note
                applied += 1
                continue
            deleted_at = local.get("deleted_at")
            if deleted_at:
                if note["updated_at"] > deleted_at:
                    index[nid] = note
                    applied += 1
                else:
                    skipped += 1
                continue
            if _note_key(note) <= _note_key(local):
                skipped += 1
                continue
            index[nid] = note
            applied += 1
        else:
            nid = change["id"]
            local = index.get(nid)
            if local is None or local.get("deleted_at"):
                skipped += 1
                continue
            local["deleted_at"] = change["updated_at"]
            deleted += 1

    return (
        list(index.values()),
        tombs,
        {"applied": applied, "skipped": skipped, "deleted": deleted},
    )
