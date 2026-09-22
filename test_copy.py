import tempfile
import unittest
from pathlib import Path

from library import Library, LibraryError


class CopyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="copy-", dir=Path(__file__).resolve().parent)
        root = Path(self.tmp.name)
        self.media, self.data = root / "media", root / "data"
        self.media.mkdir()
        self.lib = Library(self.data)
        self.lib.configure(str(self.media))

    def tearDown(self):
        self.lib.close()
        self.tmp.cleanup()

    def test_copy_is_logged_and_undoable_without_touching_source(self):
        source = self.media / "photo.jpg"
        source.write_bytes(b"original")
        self.lib.scan()
        self.lib.create_category("copies")
        resource = self.lib.resources()[0]
        operation = self.lib.copy_resources([resource["id"]], "copies")
        copied = self.media / "copies" / "photo.jpg"
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual(copied.read_bytes(), b"original")
        self.assertEqual(len(self.lib.resources()), 2)
        self.assertEqual(self.lib.logs()[0]["title"], "复制资源")
        self.lib.undo(operation["operation_id"])
        self.assertTrue(source.exists())
        self.assertFalse(copied.exists())
        self.assertEqual(len(self.lib.resources()), 1)
        self.assertEqual(len(self.lib.resources(view="trash")), 0)

    def test_folder_copy_preserves_internal_structure(self):
        folder = self.media / "album"
        (folder / "nested").mkdir(parents=True)
        (folder / "nested" / "photo.jpg").write_bytes(b"inside")
        self.lib.scan()
        self.lib.create_category("copies")
        resource = self.lib.resources()[0]
        self.lib.copy_resources([resource["id"]], "copies")
        copy = self.media / "copies" / "album" / "nested" / "photo.jpg"
        self.assertEqual(copy.read_bytes(), b"inside")
        self.assertEqual(len(self.lib.resources()), 2)  # folders remain atomic

    def test_copy_requires_destination_and_never_overwrites(self):
        source = self.media / "photo.jpg"
        source.write_bytes(b"original")
        self.lib.scan()
        resource = self.lib.resources()[0]
        with self.assertRaises(LibraryError):
            self.lib.copy_resources([resource["id"]])
        self.lib.create_category("copies")
        (self.media / "copies" / "photo.jpg").write_bytes(b"existing")
        with self.assertRaises(LibraryError):
            self.lib.copy_resources([resource["id"]], "copies")
        self.assertEqual((self.media / "copies" / "photo.jpg").read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
