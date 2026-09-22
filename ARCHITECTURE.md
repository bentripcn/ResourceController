# Architecture

The application is split into four layers:

- `library.py` owns the local SQLite index, file operations, previews metadata,
  transactions, backups and undo. It is the only layer allowed to mutate the
  user's resource folders.
- `media_tools.py` owns FFmpeg discovery, probing and atomic frame extraction.
- `rc_app/models.py` and `rc_app/controller.py` contain UI-independent filter
  state and query orchestration. They can be reused by another desktop or web
  client without importing Qt widgets.
- `rc_app/ui/` is the Qt presentation layer, split into jobs, models,
  thumbnails, widgets, player and window modules. `media_canvas.py` provides
  size-independent image/video rendering and cursor-anchored zoom;
  `interactions.py` owns smooth wheel scrolling and the grade popover;
  `duplicate_results.py` owns grouped comparison and discard selection.
  `qt_app.py` is a small
  compatibility launcher that re-exports the public classes used by older
  integrations.

Each selected target library owns its repository state at
`<target>/.resource-controller-data`. The GUI starts with an in-memory
unbound `Library`; selecting or switching a target replaces the active
repository and controller in place. This prevents indexes from different
libraries being mixed and keeps application code out of the installation
directory. A program-level SQLite database stores global tags, recent path
preferences and the cross-library operation history. Category directories use
the `{Category}` marker on disk and are decoded back to logical category names
when scanning. `ModernComboBox`, `TagChipView`, and `SeekSlider` provide shared
interaction primitives for large tag sets, predictable selectors, and direct
video timeline dragging.

The `MainWindow(data_dir=None, library=None)` API remains compatible for tests
and embedding. `app.py` and the `resource-controller` console script launch the
same Qt workbench, while `build_windows.ps1` packages the launcher with the
bundled FFmpeg runtime. `pyi_rth_qt.py` is a small PyInstaller runtime hook
that keeps the nested PySide6 Qt DLL directory discoverable on Windows.
