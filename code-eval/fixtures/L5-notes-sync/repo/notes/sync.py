"""把一批增量变更合进本地账本。

feed 形状：
    {"batch_id": "b-1", "changes": [
        {"op": "upsert", "note": {"id": "n1", "title": "…", "updated_at": "2026-03-01T10:00:00+00:00", "revision": 1}},
        {"op": "delete", "id": "n2", "updated_at": "2026-03-02T10:00:00+00:00"}
    ]}
"""


def apply_batch(notes, tombstones, batch):
    """返回 (notes, tombstones, stats)。"""
    index = {n["id"]: n for n in notes}
    applied = skipped = deleted = 0

    for change in batch.get("changes", []):
        if change.get("op") == "upsert":
            note = change["note"]
            index[note["id"]] = note
            applied += 1

    return (
        list(index.values()),
        dict(tombstones),
        {"applied": applied, "skipped": skipped, "deleted": deleted},
    )
