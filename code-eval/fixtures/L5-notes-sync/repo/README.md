# notes-sync

笔记增量同步：把一个 feed 里的变更合进本地账本。

```bash
python -m notes.cli sync --store notes.json --tombstones tombstones.json --feed data/feed-1.json
python -m unittest discover -s tests -v
```

- `notes.json`：笔记数组，一条一个对象（`id / title / body / tags / updated_at / revision`）
- `tombstones.json`：`{id: 删除时间}`，用于挡住迟到的旧 upsert
- feed：`{"batch_id": "...", "changes": [{"op": "upsert", "note": {...}}, {"op": "delete", "id": "...", "updated_at": "..."}]}`

公开 API（签名别改）：`store.load_notes` / `store.save_notes` / `store.load_tombstones` /
`store.save_tombstones` / `sync.apply_batch(notes, tombstones, batch) -> (notes, tombstones, stats)`。
`stats` 的键是 `applied` / `skipped` / `deleted`。
