"""负例：规则都实现了，但不校验输入（事务性不成立）。"""


def apply_batch(notes, tombstones, batch):
    index = {n["id"]: n for n in notes}
    tombs = dict(tombstones)
    applied = skipped = deleted = 0

    for change in batch.get("changes", []):
        if change["op"] == "upsert":
            note = dict(change["note"])
            nid = note["id"]
            if nid in tombs and note["updated_at"] <= tombs[nid]:
                skipped += 1
                continue
            local = index.get(nid)
            if local is not None and (note["updated_at"], note.get("revision", 0)) <= (
                local["updated_at"],
                local.get("revision", 0),
            ):
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
