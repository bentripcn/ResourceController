"""Regression coverage for authoritative JSON replacement imports."""

import tempfile
import unittest
from pathlib import Path

from library import Library


class ImportReplaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="replace-", dir=Path(__file__).resolve().parent)
        root = Path(self.temp.name)
        self.source = root / "media"
        self.source.mkdir()
        self.data = root / "data"
        self.lib = Library(self.data)
        self.lib.configure(str(self.source))

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def _seed(self):
        (self.source / "kept.jpg").write_bytes(b"kept")
        (self.source / "removed.jpg").write_bytes(b"removed")
        self.lib.scan()
        self.lib.create_category("travel")
        self.lib.create_category("old")
        rows = {Path(r["path"]).name: r for r in self.lib.resources()}
        self.lib.batch_update([rows["kept.jpg"]["id"]], category="travel", grade="A", add_tags=["trip"])
        self.lib.batch_update([rows["removed.jpg"]["id"]], category="old")
        self.lib.scan()
        return {Path(r["path"]).name: r for r in self.lib.resources()}

    def test_replace_applies_metadata_and_moves_omitted_resource_to_trash(self):
        rows = self._seed()
        kept = next(r for r in rows.values() if r["name"] == "kept")
        payload = {
            "format": "resource-controller",
            "version": 1,
            "categories": ["travel"],
            "tags": ["selected"],
            "resources": [{
                "id": kept["id"],
                "path": kept["path"],
                "name": "selected-kept",
                "grade": "B",
                "tags": ["selected"],
                "category": "travel",
                "type": "image",
            }],
        }
        preview = self.lib.import_data(payload, mode="replace", preview=True)
        self.assertEqual(preview["matched"], 1)
        self.assertTrue(preview["unmatched_imported"] == [])
        operation = self.lib.import_data(payload, mode="replace")
        updated = self.lib.get(kept["id"])
        self.assertEqual(updated["name"], "selected-kept")
        self.assertEqual(updated["grade"], "B")
        self.assertEqual(updated["tags"], ["selected"])
        self.assertEqual(updated["category"], "travel")
        self.assertTrue((self.source / "travel" / "B_selected-kept [selected].jpg").exists())
        self.assertEqual(len(self.lib.resources()), 1)
        self.assertEqual(len(self.lib.resources(view="trash")), 1)
        self.lib.undo(operation["operation_id"])
        self.assertEqual(len(self.lib.resources()), 2)
        restored_kept = self.lib.get(kept["id"])
        self.assertEqual(restored_kept["name"], "kept")
        self.assertEqual(restored_kept["grade"], "A")
        self.assertEqual(restored_kept["tags"], ["trip"])
        self.assertTrue((self.source / "old" / "removed.jpg").exists())

    def test_taxonomy_only_replace_returns_removed_category_to_inbox(self):
        rows = self._seed()
        removed = next(r for r in rows.values() if r["name"] == "removed")
        payload = {
            "format": "resource-controller",
            "version": 1,
            "categories": ["travel"],
            "tags": ["trip"],
        }
        operation = self.lib.import_data(payload, mode="replace")
        restored = self.lib.get(removed["id"])
        self.assertFalse(restored["trashed"])
        self.assertIsNone(restored["category"])
        self.assertTrue((self.source / "removed.jpg").exists())
        self.assertEqual([c["path"] for c in self.lib.categories()], ["travel"])
        self.lib.undo(operation["operation_id"])
        self.assertEqual([c["path"] for c in self.lib.categories()], ["old", "travel"])
        self.assertTrue((self.source / "old" / "removed.jpg").exists())


if __name__ == "__main__":
    unittest.main()
