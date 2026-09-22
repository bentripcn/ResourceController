"""Filesystem integration checks using disposable fixtures under the workspace."""
import tempfile
import subprocess
import unittest
import json
from unittest.mock import patch
from pathlib import Path

import library as library_module
from library import Library, LibraryError, build_name, default_data_dir, parse_name
from media_tools import resolve_ffmpeg


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.test-library-', dir=Path(__file__).resolve().parent)
        self.base = Path(self.temp.name)
        self.source = self.base / 'media'
        self.source.mkdir()
        self.data = self.base / 'data'
        self.library = Library(self.data)
        self.library.configure(str(self.source))

    def tearDown(self):
        self.library.close()
        self.temp.cleanup()

    def image(self, name='sunset.jpg', content=b'image content'):
        path = self.source / name
        path.write_bytes(content)
        self.library.scan()
        return next(r for r in self.library.resources() if r['path'] == str(path))

    def test_default_data_directory_stays_beside_program_or_project(self):
        with patch.dict('os.environ', {'RESOURCE_CONTROLLER_DATA_DIR': ''}, clear=False):
            expected = Path(library_module.__file__).resolve().parent / '.resource-controller-data'
            self.assertEqual(default_data_dir(), expected)

    def test_unbound_library_keeps_bootstrap_state_in_memory(self):
        library = Library.unbound()
        try:
            self.assertIsNone(library.data_dir)
            self.assertIsNone(library.source_root)
            self.assertIsNone(library.library_root)
        finally:
            library.close()

    def test_filename_roundtrip_and_folder_suffix(self):
        self.assertEqual(parse_name('A_album.2026 [travel]', True), ('A', 'album.2026', ['travel'], ''))
        self.assertEqual(parse_name('B_sunset [travel][beach].JPG'), ('B', 'sunset', ['travel', 'beach'], '.JPG'))
        self.assertEqual(build_name('sunset', 'B', ['travel', 'beach'], '.JPG'), 'B_sunset [travel][beach].JPG')
        self.assertEqual(parse_name('ordinary.jpg')[0], '')
        with self.assertRaises(LibraryError):
            build_name('sunset', 'AB')
        with self.assertRaises(LibraryError):
            build_name('sunset', 'A', ['bad[tag]'])

    def test_folder_atomic_classification_and_persistent_undo(self):
        folder = self.source / 'album.2026'
        folder.mkdir()
        inner = folder / 'nested'
        inner.mkdir()
        (inner / 'photo.jpg').write_bytes(b'unchanged')
        self.library.scan()
        resource = self.library.resources()[0]
        self.assertEqual(len(self.library.resources()), 1)
        self.library.create_category('travel/beach')
        operation = self.library.batch_update([resource['id']], grade='A', add_tags=['family'], category='travel/beach')
        moved = self.source / 'travel' / 'beach' / 'A_album.2026 [family]'
        self.assertEqual((moved / 'nested' / 'photo.jpg').read_bytes(), b'unchanged')
        self.assertFalse(any(p.name.startswith('.resource') for p in self.source.iterdir()))
        self.library.scan()
        self.assertEqual(len(self.library.resources()), 1)
        self.assertEqual(self.library.resources()[0]['category'], 'travel/beach')
        self.library.close()
        self.library = Library(self.data)
        self.library.undo(operation['operation_id'])
        self.assertEqual((folder / 'nested' / 'photo.jpg').read_bytes(), b'unchanged')

    def test_collision_never_overwrites(self):
        first = self.image('first.jpg', b'first')
        second = self.image('second.jpg', b'second')
        with self.assertRaises(LibraryError):
            self.library.batch_update([first['id'], second['id']], name='same')
        self.assertEqual((self.source / 'first.jpg').read_bytes(), b'first')
        self.assertEqual((self.source / 'second.jpg').read_bytes(), b'second')
        with self.assertRaises(LibraryError):
            self.library.batch_update([first['id']], name='second')

    def test_batch_failure_rolls_back_completed_moves(self):
        first, second = self.image('first.jpg'), self.image('second.jpg')
        original = self.library._run_step
        count = 0
        def fail_second(step, reverse=False):
            nonlocal count
            if not reverse:
                count += 1
                if count == 2:
                    raise OSError('simulated failure')
            return original(step, reverse)
        self.library._run_step = fail_second
        with self.assertRaises(LibraryError):
            self.library.batch_update([first['id'], second['id']], grade='A')
        self.assertTrue((self.source / 'first.jpg').exists())
        self.assertTrue((self.source / 'second.jpg').exists())
        self.assertTrue(all(not r['grade'] for r in self.library.resources()))

    def test_global_tag_merge_delete_and_undo(self):
        resource = self.image()
        metadata_operation = self.library.batch_update(
            [resource['id']], add_tags=['travel', 'beach'], grade='B'
        )
        self.assertEqual(self.library.logs(1)[0]['count'], 1)
        self.assertEqual(metadata_operation['count'], 1)
        operation = self.library.change_tag('travel', 'beach')
        self.assertEqual(self.library.get(resource['id'])['tags'], ['beach'])
        self.assertTrue((self.source / 'B_sunset [beach].jpg').exists())
        self.library.undo(operation['operation_id'])
        self.assertEqual(self.library.get(resource['id'])['tags'], ['travel', 'beach'])
        self.library.change_tag('travel')
        self.assertEqual(self.library.get(resource['id'])['tags'], ['beach'])

    def test_folder_cover_follows_category_rename(self):
        folder = self.source / 'album'
        folder.mkdir()
        cover = folder / 'cover.jpg'
        cover.write_bytes(b'cover')
        self.library.scan()
        resource = self.library.resources()[0]
        self.library.set_cover(resource['id'], str(cover))
        self.library.create_category('travel/beach')
        self.library.batch_update([resource['id']], category='travel/beach')
        self.library.rename_category('travel', 'holiday')
        self.assertEqual(Path(self.library.cover_path(resource['id'])).read_bytes(), b'cover')
        self.assertEqual(len(self.library.resources()), 1)
        self.library.scan()
        self.assertEqual(self.library.get(resource['id'])['category'], 'holiday/beach')

    def test_trash_undo_keeps_bytes(self):
        resource = self.image()
        operation = self.library.batch_update([resource['id']], trash=True)
        self.assertEqual(self.library.resources(), [])
        self.assertEqual(len(self.library.resources(view='trash')), 1)
        self.assertEqual(Path(self.library.get(resource['id'])['path']).read_bytes(), b'image content')
        self.library.undo(operation['operation_id'])
        self.assertEqual(Path(resource['path']).read_bytes(), b'image content')

    def test_exact_duplicates_do_not_include_folder_contents(self):
        self.image('first.jpg', b'duplicate')
        self.image('second.mp4', b'duplicate')
        folder = self.source / 'album'
        folder.mkdir()
        (folder / 'third.jpg').write_bytes(b'duplicate')
        self.library.scan()
        result = self.library.duplicates()
        self.assertEqual(len(result['groups']), 1)
        self.assertEqual(len(result['groups'][0]['resources']), 2)
        self.assertEqual((folder / 'third.jpg').read_bytes(), b'duplicate')

    def test_taxonomy_import_hierarchy_and_preview(self):
        payload = {'format': 'resource-controller', 'version': 1, 'categories': ['travel/beach'], 'tags': ['ocean']}
        self.library.import_data(payload, preview=True)
        self.assertFalse((self.source / 'travel').exists())
        self.library.import_data(payload)
        self.assertEqual([c['path'] for c in self.library.categories()], ['travel', 'travel/beach'])
        exported = self.library.export_data(categories=['travel/beach'])
        self.assertEqual(exported['categories'], ['travel', 'travel/beach'])
        self.assertEqual(exported['tags'], ['ocean'])
        self.library.undo()
        self.assertEqual(self.library.categories(), [])

    def test_replace_import_updates_existing_resource_and_is_reversible(self):
        resource = self.image('old.jpg', b'original bytes')
        payload_resource = dict(
            resource,
            name='sunset',
            grade='A',
            tags=['trip', 'beach'],
            category='travel',
        )
        payload = {
            'format': 'resource-controller',
            'version': 1,
            'categories': ['travel'],
            'tags': ['trip', 'beach'],
            'resources': [payload_resource],
        }
        preview = self.library.import_data(payload, mode='replace', preview=True)
        self.assertFalse((self.source / 'travel').exists())
        self.assertEqual(preview['matched'], 1)
        operation = self.library.import_data(payload, mode='replace')
        moved = self.source / 'travel' / 'A_sunset [trip][beach].jpg'
        self.assertTrue(moved.exists())
        current = self.library.resources()[0]
        self.assertEqual(current['category'], 'travel')
        self.assertEqual(current['grade'], 'A')
        self.assertEqual(current['tags'], ['trip', 'beach'])
        self.assertEqual(self.library.logs(1)[0]['title'], '替换分类与标签')
        self.library.undo(operation['operation_id'])
        self.assertEqual(Path(resource['path']).read_bytes(), b'original bytes')
        self.assertEqual(self.library.resources()[0]['name'], 'old')
        self.assertEqual(self.library.categories(), [])

    def test_replace_import_moves_omitted_resources_to_trash_and_undo(self):
        kept = self.image('kept.jpg', b'kept')
        omitted = self.image('omitted.jpg', b'omitted')
        payload = {
            'format': 'resource-controller',
            'version': 1,
            'categories': [],
            'tags': [],
            'resources': [dict(kept)],
        }
        operation = self.library.import_data(payload, mode='replace')
        self.assertEqual([r['name'] for r in self.library.resources()], ['kept'])
        trash = self.library.resources(view='trash')
        self.assertEqual(len(trash), 1)
        self.assertEqual(Path(trash[0]['path']).read_bytes(), b'omitted')
        self.library.undo(operation['operation_id'])
        self.assertEqual({r['name'] for r in self.library.resources()}, {'kept', 'omitted'})
        self.assertEqual(self.library.resources(view='trash'), [])
        self.assertEqual(Path(omitted['path']).read_bytes(), b'omitted')

    def test_replace_taxonomy_only_rehomes_resources_from_removed_categories(self):
        resource = self.image('classified.jpg', b'classified')
        self.library.create_category('old')
        self.library.batch_update([resource['id']], category='old')
        payload = {
            'format': 'resource-controller',
            'version': 1,
            'categories': ['new'],
            'tags': ['imported'],
        }
        operation = self.library.import_data(payload, mode='replace')
        current = self.library.resources()[0]
        self.assertIsNone(current['category'])
        self.assertEqual(Path(current['path']).parent, self.source)
        self.assertTrue((self.source / 'new').is_dir())
        self.assertEqual([c['path'] for c in self.library.categories()], ['new'])
        self.library.undo(operation['operation_id'])
        self.assertEqual(self.library.resources()[0]['category'], 'old')
        self.assertTrue((self.source / 'old' / 'classified.jpg').exists())
        self.assertFalse((self.source / 'new').exists())

    def test_selected_undo_preserves_independent_changes(self):
        first, second = self.image('first.jpg'), self.image('second.jpg')
        operation = self.library.batch_update([first['id']], grade='A')
        self.library.batch_update([second['id']], grade='B')
        self.library.undo(operation['operation_id'])
        self.assertEqual(self.library.get(first['id'])['grade'], '')
        self.assertEqual(self.library.get(second['id'])['grade'], 'B')

    def test_conflicting_undo_is_rejected(self):
        resource = self.image()
        operation = self.library.batch_update([resource['id']], grade='A')
        self.library.batch_update([resource['id']], grade='B')
        with self.assertRaises(LibraryError):
            self.library.undo(operation['operation_id'])
        self.assertTrue((self.source / 'B_sunset.jpg').exists())

    def test_category_cannot_reinterpret_atomic_folder(self):
        folder = self.source / 'album'
        folder.mkdir()
        (folder / 'cover.jpg').write_bytes(b'cover')
        self.library.scan()
        with self.assertRaises(LibraryError):
            self.library.create_category('album')
        self.assertEqual(len(self.library.resources()), 1)

    def test_category_input_is_normalized_and_rename_checks_subtree_conflict(self):
        resource = self.image('travel.jpg', b'travel')
        self.library.create_category('Trips/Beach')
        # Windows callers commonly pass a backslash separated category path.
        self.library.batch_update([resource['id']], category='Trips\\Beach')
        self.assertEqual(self.library.get(resource['id'])['category'], 'Trips/Beach')
        self.assertTrue((self.source / 'Trips' / 'Beach' / 'travel.jpg').exists())

        self.library.create_category('Archive/Beach')
        with self.assertRaises(LibraryError):
            # A/Beach -> Archive would collide with the existing Archive/Beach
            # descendant even though the Archive directory itself is present.
            self.library.rename_category('Trips', 'Archive')
        self.assertEqual(self.library.get(resource['id'])['category'], 'Trips/Beach')

    def test_parent_category_can_hold_resources_and_child_resources(self):
        parent_resource = self.image('parent.jpg', b'parent')
        child_resource = self.image('child.jpg', b'child')
        self.library.create_category('travel')
        self.library.batch_update([parent_resource['id']], category='travel')
        # A parent is both a valid final classification and a namespace for
        # nested classifications.  Browsing the parent must include both.
        self.library.create_category('travel/coast')
        self.library.batch_update([child_resource['id']], category='travel/coast')
        self.assertEqual(
            {r['name'] for r in self.library.resources(category='travel')},
            {'parent', 'child'},
        )
        self.assertEqual(self.library.stats(category='travel')['images'], 2)
        self.assertEqual(
            {c['path']: c['count'] for c in self.library.categories()},
            {'travel': 2, 'travel/coast': 1},
        )

    def test_target_can_be_chosen_after_scanning_before_classification(self):
        self.image('unclassified.jpg', b'bytes')
        target = self.base / 'target'
        target.mkdir()
        self.library.configure(str(self.source), str(target))
        self.assertEqual(self.library.source_root, self.source)
        self.assertEqual(self.library.library_root, target)
        self.library.create_category('archive')
        resource = self.library.resources()[0]
        self.library.batch_update([resource['id']], category='archive')
        self.assertTrue((target / 'archive' / 'unclassified.jpg').exists())

    def test_target_library_relocation_moves_categories_and_is_undoable(self):
        resource = self.image('coast.jpg', b'coast')
        self.library.create_category('travel/coast')
        self.library.batch_update([resource['id']], category='travel/coast')
        target = self.base / 'target'
        target.mkdir()
        self.library.configure(str(self.source), str(target))
        moved = target / 'travel' / 'coast' / 'coast.jpg'
        self.assertTrue(moved.exists())
        self.assertFalse((self.source / 'travel').exists())
        self.assertEqual(Path(self.library.get(resource['id'])['path']), moved)
        self.library.undo()
        self.assertTrue((self.source / 'travel' / 'coast' / 'coast.jpg').exists())
        self.assertEqual(self.library.library_root, self.source)

    def test_undo_accepts_operation_journal_from_before_settings_snapshots(self):
        resource = self.image('legacy.jpg', b'legacy')
        operation = self.library.batch_update([resource['id']], grade='A')
        payload = json.loads(
            self.library.db.execute(
                'SELECT payload FROM operations WHERE id=?', (operation['operation_id'],)
            ).fetchone()[0]
        )
        payload['before'].pop('settings', None)
        payload['after'].pop('settings', None)
        self.library.db.execute(
            'UPDATE operations SET payload=? WHERE id=?',
            (json.dumps(payload, ensure_ascii=False), operation['operation_id']),
        )
        self.library.db.commit()
        self.library.undo(operation['operation_id'])
        self.assertTrue((self.source / 'legacy.jpg').exists())
        self.assertEqual(self.library.get(resource['id'])['grade'], '')

    def test_similar_video_detects_reencoded_copy_without_deleting_files(self):
        executable = resolve_ffmpeg()
        if not executable: self.skipTest('FFmpeg runtime is not installed')
        first = self.source / 'original.mp4'
        second = self.source / 'smaller.mp4'
        unrelated = self.source / 'unrelated.mp4'
        def run(arguments):
            subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-y', *arguments],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30)
        run(['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=10', '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(first)])
        run(['-i', str(first), '-vf', 'scale=160:90', '-c:v', 'libx264', '-crf', '32', str(second)])
        run(['-f', 'lavfi', '-i', 'color=c=blue:size=160x90:rate=10', '-t', '2', '-c:v', 'libx264', str(unrelated)])
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        self.library.scan()
        result = self.library.duplicates(mode='similar')
        groups = [{r['name'] for r in group['resources']} for group in result['groups']]
        self.assertIn({'original', 'smaller'}, groups)
        self.assertFalse(any('unrelated' in group for group in groups))
        self.assertEqual(result['errors'], [])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})


if __name__ == '__main__':
    unittest.main()
