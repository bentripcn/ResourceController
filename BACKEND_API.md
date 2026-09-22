# Local library service

`library.py` has no UI dependencies. The desktop starts with `Library.unbound()` (an in-memory bootstrap session), then creates or opens `.resource-controller-data` inside the selected target library. A constructor path is still supported for tests and embedding. SQLite, cache, trash, journal and backups stay beside the target library, so switching libraries switches indexes as well. The program database stores global tags, recent path settings and cross-library operation history. Category folders are written as `{Category}` directories and decoded during scans. Methods raise `LibraryError` with user-facing Chinese messages.

```python
library = Library(target_root / '.resource-controller-data')
library.set_library_root(target_root)  # optional: target can be selected first
library.configure(source_root, library_root=None)  # defaults managed root to source
library.scan()  # {'count': ..., 'errors': [...]}
library.settings()  # source_root, library_root, data_dir
library.resources(category=None, grade='', tags=None, type='', query='', recursive=True, view='all')
library.get(resource_id)
library.stats()
library.categories()  # [{path, name, parent, count}]
library.tags()  # [{name, count}]
```

Resource dictionaries: `id, path, name, grade, tags` (list), `category` (None=inbox), `type` (`image/video/folder`), `extension`, `size`, `mtime`, `trashed`, `cover` (relative folder cover reference). Unmanaged files start ungraded (`grade=''`), avoiding silently assigning C. `resources(view='trash')` lists discarded files, `view='inbox'` lists inbox. Category filtering includes descendants. Selected tags use AND.

```python
library.create_category('旅行/海边', preview=False)
library.rename_category('旅行/海边', '旅行/沙滩', preview=False)
library.delete_category('旅行', preview=False)  # entire branch to internal trash
library.batch_update(ids, grade=None, name=None, add_tags=None,
                     remove_tags=None, tags=None, category=None,
                     trash=False, preview=False)
library.copy_resources(ids, category, preview=False)
library.add_tag('海边')
library.change_tag('海边', '海岸', preview=False)  # rename or merge
library.change_tag('海边', None, preview=False)  # delete global tag, rebuild filenames
library.set_cover(id, absolute_image_path_or_None)
library.cover_path(id)
library.logs(limit=100)
library.undo(operation_id=None, preview=False)
library.duplicates(mode='exact', category=None, ids=None, threshold=8, expand_folder=None)
library.export_data(categories=None, tags=None, include_resources=True)
library.import_data(payload_dict, mode='merge', preview=False)
library.backup()
library.close()
```

The API accepts `preview=True` when a caller needs a file-change plan (`from/to` or `path`). The desktop UI executes ordinary reversible edits directly and asks for a second confirmation only before moving resources or categories into the internal trash. `name` supports `{name}` and `{n}`; `category=''` moves to inbox, omitted category keeps current. Exact dedup uses SHA-256; similar-image dedup uses Pillow dHash and similar-video dedup samples three representative frames via FFmpeg. Similar videos with fewer than two decoded frames are skipped with an error. `expand_folder` is an explicit advanced option for one indexed folder resource: children are temporary result dictionaries (`id` starts with `temporary:`), never inserted into SQLite or changed; the result includes `temporary_scope` and `temporary=True`. The caller must show a warning and must not pass temporary IDs to mutating APIs. No dedup operation deletes or moves files. JSON import supports taxonomy and optional resource metadata. `merge` keeps active resources; `replace` makes the imported taxonomy authoritative, applies matching name/grade/tags/category metadata, and moves omitted active resources to the internal trash (or returns resources from removed categories to the inbox when metadata is absent). Replace remains previewable, journalled and undoable.

Folders are atomic: scans only enumerate source root, managed root, and explicitly registered category directories. Their internals are never indexed or renamed. Cover paths are relative to folder resources and follow moves. Any user-created category can hold resources and child categories; querying a parent includes its descendants. Move/name/copy collisions abort before mutation, never overwrite. `copy_resources` copies files or whole atomic folders to a specified category, preserves the source, creates new resource IDs, logs the operation, and makes undo move the copy into internal trash. Persistent operation journals compensate failures and recover interrupted operations. Undo checks later conflicting metadata changes and refuses path collisions. Batches of 20+ file changes trigger database backups.
