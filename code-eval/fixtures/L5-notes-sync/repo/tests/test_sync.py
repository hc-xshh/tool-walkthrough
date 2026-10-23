import unittest

from notes.sync import apply_batch


def note(nid, ts, rev=1, title=None):
    return {
        "id": nid,
        "title": title or nid,
        "body": "",
        "tags": [],
        "updated_at": ts,
        "revision": rev,
    }


class SyncTest(unittest.TestCase):
    def test_new_note_inserted(self):
        notes, tombstones, stats = apply_batch(
            [],
            {},
            {"changes": [{"op": "upsert", "note": note("n1", "2026-03-01T00:00:00+00:00")}]},
        )
        self.assertEqual([n["id"] for n in notes], ["n1"])
        self.assertEqual(stats["applied"], 1)
        self.assertEqual(tombstones, {})

    def test_existing_note_replaced_by_newer(self):
        local = [note("n1", "2026-03-01T00:00:00+00:00", 1, "old")]
        newer = note("n1", "2026-03-02T00:00:00+00:00", 1, "new")
        notes, _, stats = apply_batch(
            local, {}, {"changes": [{"op": "upsert", "note": newer}]}
        )
        self.assertEqual(notes[0]["title"], "new")
        self.assertEqual(stats["applied"], 1)

    def test_empty_batch(self):
        notes, tombstones, stats = apply_batch([], {}, {"changes": []})
        self.assertEqual(notes, [])
        self.assertEqual(tombstones, {})
        self.assertEqual(stats, {"applied": 0, "skipped": 0, "deleted": 0})


if __name__ == "__main__":
    unittest.main()
