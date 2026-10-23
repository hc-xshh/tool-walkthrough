"""L5 隐藏验收：冲突合并、墓碑、幂等、事务、旧账本兼容。"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from notes.sync import apply_batch

ROOT = Path(__file__).resolve().parents[1]


def note(nid, ts, rev=1, title=None):
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


class SyncAccept(unittest.TestCase):
    def test_older_upsert_is_skipped(self):
        local = [note("n1", "2026-03-02T00:00:00+00:00", 1, "new")]
        notes, _, stats = apply_batch(
            local, {}, {"changes": [upsert(note("n1", "2026-03-01T00:00:00+00:00", 1, "old"))]}
        )
        self.assertEqual(notes[0]["title"], "new")
        self.assertEqual((stats["applied"], stats["skipped"]), (0, 1))

    def test_same_timestamp_higher_revision_wins(self):
        local = [note("n1", "2026-03-02T00:00:00+00:00", 1, "v1")]
        notes, _, stats = apply_batch(
            local, {}, {"changes": [upsert(note("n1", "2026-03-02T00:00:00+00:00", 2, "v2"))]}
        )
        self.assertEqual(notes[0]["title"], "v2")
        self.assertEqual(stats["applied"], 1)

    def test_same_timestamp_and_revision_is_skipped(self):
        local = [note("n1", "2026-03-02T00:00:00+00:00", 2, "v2")]
        notes, _, stats = apply_batch(
            local, {}, {"changes": [upsert(note("n1", "2026-03-02T00:00:00+00:00", 2, "v2b"))]}
        )
        self.assertEqual(notes[0]["title"], "v2")
        self.assertEqual(stats["skipped"], 1)

    def test_delete_removes_note_and_records_tombstone(self):
        local = [note("n1", "2026-03-02T00:00:00+00:00")]
        ts = "2026-03-05T00:00:00+00:00"
        notes, tombstones, stats = apply_batch(local, {}, {"changes": [delete("n1", ts)]})
        self.assertEqual(notes, [])
        self.assertEqual(tombstones["n1"], ts)
        self.assertEqual(stats["deleted"], 1)

    def test_stale_upsert_does_not_revive(self):
        tombstones = {"n1": "2026-03-05T00:00:00+00:00"}
        notes, tombs, stats = apply_batch(
            [], tombstones, {"changes": [upsert(note("n1", "2026-03-04T00:00:00+00:00"))]}
        )
        self.assertEqual(notes, [])
        self.assertIn("n1", tombs)
        self.assertEqual(stats["skipped"], 1)

    def test_newer_upsert_revives_and_clears_tombstone(self):
        tombstones = {"n1": "2026-03-05T00:00:00+00:00"}
        notes, tombs, stats = apply_batch(
            [], tombstones, {"changes": [upsert(note("n1", "2026-03-06T00:00:00+00:00"))]}
        )
        self.assertEqual([n["id"] for n in notes], ["n1"])
        self.assertNotIn("n1", tombs)
        self.assertEqual(stats["applied"], 1)

    def test_replay_is_idempotent(self):
        batch = {
            "changes": [
                upsert(note("n1", "2026-03-02T00:00:00+00:00")),
                delete("n2", "2026-03-03T00:00:00+00:00"),
            ]
        }
        notes, tombstones, first = apply_batch([], {}, batch)
        notes2, tombstones2, second = apply_batch(notes, tombstones, batch)
        # 任务书只要求「重放不产生改动、applied 为 0」，不约束 skipped/deleted 的计数口径
        self.assertEqual(sorted(n["id"] for n in notes2), sorted(n["id"] for n in notes))
        self.assertEqual(tombstones2, tombstones)
        self.assertEqual(second["applied"], 0)

    def test_invalid_change_leaves_inputs_untouched(self):
        notes = [note("n1", "2026-03-02T00:00:00+00:00")]
        tombstones = {"n9": "2026-03-01T00:00:00+00:00"}
        notes_before, tombs_before = copy.deepcopy(notes), copy.deepcopy(tombstones)
        batch = {
            "changes": [
                upsert(note("n2", "2026-03-03T00:00:00+00:00")),
                {"op": "rename", "id": "n1"},
            ]
        }
        with self.assertRaises(ValueError):
            apply_batch(notes, tombstones, batch)
        self.assertEqual(notes, notes_before)
        self.assertEqual(tombstones, tombs_before)

    def test_missing_updated_at_is_rejected(self):
        with self.assertRaises(ValueError):
            apply_batch([], {}, {"changes": [{"op": "upsert", "note": {"id": "n1", "title": "x"}}]})

    def run_cli(self, store, tombstones, feed):
        return subprocess.run(
            [
                sys.executable, "-m", "notes.cli", "sync",
                "--store", str(store), "--tombstones", str(tombstones), "--feed", str(feed),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_cli_writes_files_and_prints_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = tmp / "notes.json"
            tombs = tmp / "tombstones.json"
            feed = tmp / "feed.json"
            store.write_text(
                json.dumps([note("legacy", "2026-01-01T00:00:00+00:00")]), encoding="utf-8"
            )
            feed.write_text(
                json.dumps(
                    {
                        "batch_id": "b-1",
                        "changes": [
                            upsert(note("n1", "2026-03-02T00:00:00+00:00")),
                            upsert(note("n2", "2026-03-03T00:00:00+00:00")),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            res = self.run_cli(store, tombs, feed)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(json.loads(res.stdout)["applied"], 2)
            ids = {n["id"] for n in json.loads(store.read_text(encoding="utf-8"))}
            self.assertEqual(ids, {"legacy", "n1", "n2"})
            self.assertEqual(json.loads(tombs.read_text(encoding="utf-8")), {})

    def test_cli_invalid_feed_exits_2_and_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = tmp / "notes.json"
            tombs = tmp / "tombstones.json"
            feed = tmp / "feed.json"
            store.write_text(
                json.dumps([note("n1", "2026-03-02T00:00:00+00:00")]), encoding="utf-8"
            )
            tombs.write_text("{}", encoding="utf-8")
            feed.write_text(
                json.dumps({"changes": [{"op": "upsert", "note": {"id": "", "updated_at": "x"}}]}),
                encoding="utf-8",
            )
            before_store = store.read_bytes()
            before_tombs = tombs.read_bytes()
            res = self.run_cli(store, tombs, feed)
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertEqual(store.read_bytes(), before_store)
            self.assertEqual(tombs.read_bytes(), before_tombs)


if __name__ == "__main__":
    unittest.main()
