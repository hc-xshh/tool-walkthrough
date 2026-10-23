"""L6 隐藏验收：第二轮把物理删除改成软删除，且第一轮的合并规则不能被改坏。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from notes.sync import apply_batch

ROOT = Path(__file__).resolve().parents[1]
FIXED = "2026-03-01T00:00:00+00:00"


def note(nid, ts=FIXED, rev=1, title=None):
    return {
        "id": nid,
        "title": title or nid,
        "body": "",
        "tags": [],
        "updated_at": ts,
        "revision": rev,
    }


def upsert(n):
    return {"op": "upsert", "note": n}


def delete(nid, ts):
    return {"op": "delete", "id": nid, "updated_at": ts}


def run_cli(*args, cwd=ROOT):
    return subprocess.run(
        [sys.executable, "-m", "notes.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class SoftDeleteAccept(unittest.TestCase):
    def test_delete_keeps_record_with_deleted_at(self):
        ts = "2026-03-05T00:00:00+00:00"
        notes, tombstones, stats = apply_batch(
            [note("n1")], {}, {"changes": [delete("n1", ts)]}
        )
        self.assertEqual(len(notes), 1, "软删除不应把记录从账本里删掉")
        self.assertEqual(notes[0]["deleted_at"], ts)
        self.assertEqual(tombstones, {}, "软删除不再写墓碑")
        self.assertEqual(stats["deleted"], 1)

    def test_deleting_twice_counts_once(self):
        ts = "2026-03-05T00:00:00+00:00"
        notes, _, first = apply_batch([note("n1")], {}, {"changes": [delete("n1", ts)]})
        notes, _, second = apply_batch(notes, {}, {"changes": [delete("n1", ts)]})
        self.assertEqual(first["deleted"], 1)
        self.assertEqual(second["deleted"], 0)
        self.assertEqual(second["skipped"], 1)

    def test_stale_upsert_does_not_revive(self):
        notes = [
            {**note("n1", "2026-03-02T00:00:00+00:00"), "deleted_at": "2026-03-05T00:00:00+00:00"}
        ]
        notes, _, stats = apply_batch(
            notes, {}, {"changes": [upsert(note("n1", "2026-03-04T00:00:00+00:00", 1, "旧"))]}
        )
        self.assertEqual(notes[0]["deleted_at"], "2026-03-05T00:00:00+00:00")
        self.assertEqual(notes[0]["title"], "n1")
        self.assertEqual(stats["skipped"], 1)

    def test_newer_upsert_revives(self):
        notes = [
            {**note("n1", "2026-03-02T00:00:00+00:00"), "deleted_at": "2026-03-05T00:00:00+00:00"}
        ]
        notes, _, stats = apply_batch(
            notes, {}, {"changes": [upsert(note("n1", "2026-03-06T00:00:00+00:00", 1, "复活"))]}
        )
        self.assertEqual(notes[0]["title"], "复活")
        self.assertNotIn("deleted_at", notes[0])
        self.assertEqual(stats["applied"], 1)

    def test_legacy_tombstones_are_migrated(self):
        tombstones = {"n1": "2026-03-05T00:00:00+00:00"}
        notes, tombs, stats = apply_batch(
            [note("n1", "2026-03-02T00:00:00+00:00")], tombstones, {"changes": []}
        )
        self.assertEqual(notes[0]["deleted_at"], "2026-03-05T00:00:00+00:00")
        self.assertEqual(tombs, {}, "迁移后墓碑应清空")
        self.assertEqual(stats, {"applied": 0, "skipped": 0, "deleted": 0})

    def test_replay_is_idempotent(self):
        batch = {
            "changes": [
                upsert(note("n1", "2026-03-02T00:00:00+00:00")),
                delete("n2", "2026-03-03T00:00:00+00:00"),
            ]
        }
        notes, tombs, _ = apply_batch([note("n2")], {}, batch)
        notes2, tombs2, second = apply_batch(notes, tombs, batch)
        self.assertEqual(sorted(n["id"] for n in notes2), sorted(n["id"] for n in notes))
        self.assertEqual(tombs2, tombs)
        self.assertEqual(second["applied"], 0)
        self.assertEqual(second["deleted"], 0)

    def test_revision_breaks_timestamp_tie(self):
        local = [note("n1", FIXED, 1, "v1")]
        notes, _, stats = apply_batch(
            local, {}, {"changes": [upsert(note("n1", FIXED, 2, "v2"))]}
        )
        self.assertEqual(notes[0]["title"], "v2")
        self.assertEqual(stats["applied"], 1)

    def test_older_upsert_still_skipped(self):
        local = [note("n1", "2026-03-02T00:00:00+00:00", 1, "new")]
        notes, _, stats = apply_batch(
            local, {}, {"changes": [upsert(note("n1", "2026-03-01T00:00:00+00:00", 1, "old"))]}
        )
        self.assertEqual(notes[0]["title"], "new")
        self.assertEqual(stats["skipped"], 1)

    def test_invalid_batch_keeps_files_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = tmp / "notes.json"
            tombs = tmp / "tombstones.json"
            feed = tmp / "feed.json"
            store.write_text(json.dumps([note("n1")]), encoding="utf-8")
            tombs.write_text(json.dumps({"n9": FIXED}), encoding="utf-8")
            feed.write_text(json.dumps({"changes": [{"op": "rename", "id": "n1"}]}), encoding="utf-8")
            before_store, before_tombs = store.read_bytes(), tombs.read_bytes()

            res = run_cli(
                "sync", "--store", str(store), "--tombstones", str(tombs), "--feed", str(feed)
            )
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertEqual(store.read_bytes(), before_store)
            self.assertEqual(tombs.read_bytes(), before_tombs)

    def test_cli_list_hides_deleted_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = tmp / "notes.json"
            tombs = tmp / "tombstones.json"
            feed = tmp / "feed.json"
            store.write_text(
                json.dumps([note("n1"), note("n2")]), encoding="utf-8"
            )
            tombs.write_text("{}", encoding="utf-8")
            feed.write_text(
                json.dumps({"changes": [delete("n2", "2026-03-05T00:00:00+00:00")]}),
                encoding="utf-8",
            )
            res = run_cli(
                "sync", "--store", str(store), "--tombstones", str(tombs), "--feed", str(feed)
            )
            self.assertEqual(res.returncode, 0, res.stderr)

            visible = run_cli("list", "--store", str(store))
            self.assertEqual(visible.returncode, 0, visible.stderr)
            ids = [n["id"] for n in json.loads(visible.stdout)]
            self.assertEqual(ids, ["n1"])

            everything = run_cli("list", "--store", str(store), "--include-deleted")
            ids = [n["id"] for n in json.loads(everything.stdout)]
            self.assertEqual(sorted(ids), ["n1", "n2"])


if __name__ == "__main__":
    unittest.main()
