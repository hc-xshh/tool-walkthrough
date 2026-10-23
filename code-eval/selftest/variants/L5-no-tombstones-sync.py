"""负例：做了冲突合并和删除，但不看墓碑。"""


def apply_batch(notes, tombstones, batch):
    index = {n["id"]: n for n in notes}
    tombs = dict(tombstones)
    applied = skipped = deleted = 0

    for change in batch.get("changes", []):
        if change["op"] == "upsert":
            note = dict(change["note"])
            nid = note["id"]
            local = index.get(nid)
            if local is not None and (note["updated_at"], note.get("revision", 0)) <= (
                local["updated_at"],
                local.get("revision", 0),
            ):
                skipped += 1
                continue
            index[nid] = note
            applied += 1
        else:
            nid = change["id"]
            if nid in index:
                del index[nid]
                deleted += 1
            else:
                skipped += 1
            tombs[nid] = change["updated_at"]

    return (
        list(index.values()),
        tombs,
        {"applied": applied, "skipped": skipped, "deleted": deleted},
    )
