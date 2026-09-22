"""Focused regression tests for duplicate detection safety and grouping."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from library import Library, LibraryError


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dup-", dir=Path(__file__).resolve().parent)
        root = Path(self.tmp.name)
        self.media, self.data = root / "media", root / "data"
        self.media.mkdir()
        self.lib = Library(self.data)
        self.lib.configure(str(self.media))

    def tearDown(self):
        self.lib.close()
        self.tmp.cleanup()

    def test_similar_groups_are_not_transitive(self):
        paths = [self.media / name for name in ("a.mp4", "b.mp4", "c.mp4")]
        for path in paths:
            path.write_bytes(b"x")
        self.lib.scan()
        # A~B and B~C are within threshold; A~C is deliberately not.
        values = {str(paths[0]): [(0, (0, 0, 0)),],
                  str(paths[1]): [(1, (0, 0, 0)),],
                  str(paths[2]): [(511, (0, 0, 0)),]}
        # A single frame is rejected by _video_hashes, so return two samples
        # to exercise the real multi-frame grouping path.
        values = {path: hashes * 2 for path, hashes in values.items()}
        with patch.object(Library, "_video_hashes", staticmethod(lambda path, ffmpeg=None: values[path])):
            result = self.lib.duplicates(mode="similar", threshold=8)
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual({r["path"] for r in result["groups"][0]["resources"]}, {str(paths[0]), str(paths[1])})

    def test_folder_expansion_is_explicit_and_ephemeral(self):
        folder = self.media / "opaque"
        folder.mkdir()
        (folder / "one.jpg").write_bytes(b"same")
        (folder / "two.jpg").write_bytes(b"same")
        self.lib.scan()
        owner = self.lib.resources()[0]
        default = self.lib.duplicates(mode="exact")
        self.assertEqual(default["scanned"], 0)
        result = self.lib.duplicates(mode="exact", expand_folder=owner["path"])
        self.assertTrue(result["temporary"])
        self.assertEqual(result["temporary_scope"], str(folder.resolve()))
        self.assertEqual(result["scanned"], 2)
        self.assertTrue(result["groups"][0]["resources"][0]["id"].startswith("temporary:"))
        # Expansion must not add children to the persistent index.
        self.assertEqual(len(self.lib.resources()), 1)
        with self.assertRaises(LibraryError):
            self.lib.duplicates(mode="exact", expand_folder=self.media / "not-indexed")

    def test_unknown_ffmpeg_is_actionable(self):
        path = self.media / "clip.mp4"
        path.write_bytes(b"video")
        with patch("library.resolve_ffmpeg", return_value=None):
            with self.assertRaises(LibraryError) as error:
                Library._video_hashes(str(path))
        self.assertIn("FFmpeg", str(error.exception))

    def test_inbox_sources_can_compare_against_entire_library(self):
        inbox = self.media / "inbox.png"
        library_copy = self.media / "library-copy.png"
        inbox.write_bytes(b"same-content")
        library_copy.write_bytes(b"same-content")
        self.lib.scan()
        rows = self.lib.resources()
        inbox_id = next(row["id"] for row in rows if row["path"] == str(inbox))
        copy_id = next(row["id"] for row in rows if row["path"] == str(library_copy))
        self.lib.create_category("已整理", preview=False)
        self.lib.batch_update([copy_id], category="已整理", preview=False)

        result = self.lib.duplicates(
            mode="exact", ids=[inbox_id], compare_all=True, source_ids=[inbox_id]
        )
        self.assertEqual(result["scanned"], 2)
        self.assertEqual(
            {resource["id"] for resource in result["groups"][0]["resources"]},
            {inbox_id, copy_id},
        )


if __name__ == "__main__":
    unittest.main()
