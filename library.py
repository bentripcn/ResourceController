"""ResourceController's local, UI-independent library service.

Only registered category directories are scanned. Every other directory is an
opaque resource. The database, previews, backups and trash live in ``data_dir``.
File operations are collision checked, journalled and reversible.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from media_tools import resolve_ffmpeg

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".avif",
    ".raw",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".dng",
    ".orf",
    ".rw2",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".mts",
    ".m2ts",
    ".3gp",
}
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)


def _json_load(value, default=None):
    """Decode nullable JSON columns from databases created during testing."""
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list, tuple, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _pixel_values(image):
    """Read Pillow pixels across Pillow 10 through 14 without deprecation noise."""
    getter = getattr(image, "get_flattened_data", None)
    if getter:
        return list(getter())
    # Pillow <=13 exposes getdata(); avoid the deprecated method warning where
    # possible while retaining compatibility with older runtime wheels.
    return [image.getpixel((x, y)) for y in range(image.height) for x in range(image.width)]


class LibraryError(ValueError):
    """A user-actionable library validation error."""


def clean_component(value: str, *, tag: bool = False) -> str:
    value = str(value).strip()
    if not value or value in {".", ".."} or value.endswith((".", " ")):
        raise LibraryError("名称不能为空，也不能以句点或空格结尾。")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or (tag and re.search(r"[\[\]]", value)):
        raise LibraryError("名称包含文件系统不允许的字符。")
    if RESERVED.match(value):
        raise LibraryError("此名称是系统保留名称。")
    if len(value) > 180:
        raise LibraryError("名称过长，请缩短至 180 个字符以内。")
    return value


def parse_name(filename: str, is_folder: bool = False) -> tuple[str, str, list[str], str]:
    """Return grade, original name, flat tags, extension (folders have none)."""
    ext = "" if is_folder else Path(filename).suffix
    stem = filename if not ext else filename[: -len(ext)]
    grade = ""
    if re.match(r"^[ABC]_", stem):
        grade, stem = stem[0], stem[2:]
    match = re.search(r"\s+((?:\[[^\[\]]+\])+)$", stem)
    tags: list[str] = []
    if match:
        tags = list(dict.fromkeys(re.findall(r"\[([^\[\]]+)\]", match.group(1))))
        stem = stem[: match.start()]
    return grade, stem, tags, ext


def build_name(
    name: str, grade: str = "", tags: list[str] | None = None, extension: str = ""
) -> str:
    name = clean_component(name)
    if grade not in {"", "A", "B", "C"}:
        raise LibraryError("分级只能为 A、B、C 或未分级。")
    tags = list(dict.fromkeys(clean_component(t, tag=True) for t in (tags or [])))
    result = (f"{grade}_" if grade else "") + name
    if tags:
        result += " " + "".join(f"[{tag}]" for tag in tags)
    result += extension
    if len(result) > 240:
        raise LibraryError("完整文件名过长，请减少名称或标签长度。")
    return result


def default_data_dir() -> Path:
    configured = os.environ.get("RESOURCE_CONTROLLER_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    # Keep program records beside the portable application rather than in a
    # per-user C: profile.  Source runs use this module's project directory;
    # PyInstaller builds use the executable's one-folder distribution.
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / ".resource-controller-data"


def global_data_path() -> Path:
    """Application-wide metadata database (tags, preferences and history)."""
    configured = os.environ.get("RESOURCE_CONTROLLER_GLOBAL_DB")
    if configured:
        return Path(configured).expanduser()
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / ".resource-controller-global.sqlite3"


def _key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class Library:
    def __init__(self, data_dir: str | Path | None = None, *, ephemeral: bool = False):
        if ephemeral:
            self._data_dir_explicit = False
            self.data_dir = None
            self._lock = threading.RLock()
            self.db = sqlite3.connect(":memory:", check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self._create_schema()
            self._open_global_db()
            return
        self._data_dir_explicit = data_dir is not None
        self.data_dir = Path(data_dir or default_data_dir()).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for folder in ("cache", "backups", "trash"):
            (self.data_dir / folder).mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.data_dir / "library.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        self._recover()
        self._open_global_db()
        self._sync_global_tags()

    @classmethod
    def unbound(cls):
        """Create an empty session library without writing beside the app."""
        return cls(ephemeral=True)

    def _create_schema(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS categories(path TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS tags(name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS resources(
                id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                grade TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]',
                category TEXT, type TEXT NOT NULL, extension TEXT NOT NULL DEFAULT '',
                size INTEGER NOT NULL DEFAULT 0, mtime REAL NOT NULL DEFAULT 0,
                trashed INTEGER NOT NULL DEFAULT 0, cover TEXT,
                fingerprint TEXT NOT NULL DEFAULT '', hash TEXT, hash_signature TEXT);
            CREATE TABLE IF NOT EXISTS operations(
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL, error TEXT);
        """)
        self.db.commit()

    def _open_global_db(self):
        path = global_data_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.global_db = sqlite3.connect(path, check_same_thread=False)
        self.global_db.row_factory = sqlite3.Row
        self.global_db.executescript("""
            CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS global_tags(name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS global_operations(
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL,
                count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'done',
                library_root TEXT
            );
        """)
        columns = {row[1] for row in self.global_db.execute("PRAGMA table_info(global_operations)")}
        if "library_root" not in columns:
            self.global_db.execute("ALTER TABLE global_operations ADD COLUMN library_root TEXT")
        self.global_db.commit()

    def _sync_global_tags(self):
        if not getattr(self, "global_db", None):
            return
        names = [row[0] for row in self.db.execute("SELECT name FROM tags")]
        if names:
            self.global_db.executemany("INSERT OR IGNORE INTO global_tags VALUES (?)", [(name,) for name in names])
            self.global_db.commit()

    def close(self):
        with self._lock:
            self.db.close()
            if getattr(self, "global_db", None):
                self.global_db.close()

    def _setting(self, key: str, default: Any = None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return _json_load(row[0], default) if row else default

    def settings(self) -> dict:
        with self._lock:
            result = {
                row["key"]: _json_load(row["value"])
                for row in self.db.execute("SELECT * FROM settings")
            }
            if getattr(self, "global_db", None):
                result.update({
                    row["key"]: _json_load(row["value"])
                    for row in self.global_db.execute("SELECT * FROM app_settings")
                })
            result["data_dir"] = str(self.data_dir) if self.data_dir else None
            return result

    @property
    def source_root(self) -> Path | None:
        value = self._setting("source_root")
        return Path(value) if value else None

    @property
    def library_root(self) -> Path | None:
        value = self._setting("library_root")
        return Path(value) if value else None

    def set_library_root(self, library_root: str | Path) -> dict:
        """Bind this session to a target resource library without a source yet.

        The target directory is the owner of the repository data.  This small
        step is intentionally separate from :meth:`configure` so the UI can
        let users choose the target library first and attach an original
        folder afterwards.
        """
        with self._lock:
            managed = Path(library_root).expanduser().resolve()
            if not managed.is_dir():
                raise LibraryError("目标库必须是已存在的文件夹。")
            self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES (?, ?)",
                ("library_root", json.dumps(str(managed))),
            )
            self.db.commit()
            if getattr(self, "global_db", None):
                self.global_db.execute("INSERT OR REPLACE INTO app_settings VALUES (?,?)", ("last_library_root", json.dumps(str(managed))))
                self.global_db.commit()
            return self.settings()

    def configure(self, source_root: str, library_root: str | None = None) -> dict:
        with self._lock:
            source = Path(source_root).expanduser().resolve()
            # Preserve a target selected in advance when the caller attaches
            # the original folder later; otherwise default to the source.
            managed = Path(library_root or self.library_root or source_root).expanduser().resolve()
            if not source.is_dir() or not managed.is_dir():
                raise LibraryError("原始目录和分类库目录必须是已存在的文件夹。")
            old_source, old_managed = self.source_root, self.library_root
            if old_source and source != old_source:
                # A resource index is bound to the original-library paths.  A
                # different source therefore needs its own data directory;
                # otherwise old records could accidentally be interpreted as
                # resources in the newly selected library.
                count = self.db.execute("SELECT count(*) FROM resources").fetchone()[0]
                if count:
                    raise LibraryError("当前已有资源，请使用独立的数据目录建立另一资源库。")
                if self.db.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
                    raise LibraryError("当前已有分类，请使用独立的数据目录建立另一资源库。")
            if old_source and source == old_source and managed != old_managed:
                # Relocate each top-level category as an atomic directory.
                # This preserves resources, nested categories and opaque
                # folder resources without inspecting their internals.
                categories = [r[0] for r in self.db.execute("SELECT path FROM categories")]
                old_root = old_managed or old_source
                if old_root is None:
                    raise LibraryError("尚未设置原始目录。")
                roots = [category for category in categories if "/" not in category]
                steps = []
                for category in roots:
                    old_path = self._category_path_at(old_root, category)
                    new_path = managed.joinpath(*(f"{{{part}}}" for part in category.split("/")))
                    if _inside(managed, old_path):
                        raise LibraryError("目标库不能位于现有分类文件夹内部。")
                    if not old_path.is_dir():
                        raise LibraryError(f"分类文件夹不存在，无法迁移：{category}")
                    if new_path.exists():
                        raise LibraryError(f"目标库已有同名分类，未覆盖：{category}")
                    steps.append({"action": "move", "from": str(old_path), "to": str(new_path)})

                def migrate_settings():
                    # Active resource paths follow the moved category tree;
                    # trashed entries stay in the app-owned trash directory.
                    for row in self.db.execute(
                        "SELECT id,path,category,trashed FROM resources WHERE category IS NOT NULL"
                    ).fetchall():
                        if row["trashed"]:
                            continue
                        current = Path(row["path"])
                        try:
                            relative = current.relative_to(old_root)
                        except ValueError as exc:
                            raise LibraryError("资源路径不在当前目标库中，无法迁移目标库。") from exc
                        self.db.execute(
                            "UPDATE resources SET path=? WHERE id=?",
                            (str(managed / relative), row["id"]),
                        )
                    self.db.executemany(
                        "INSERT OR REPLACE INTO settings VALUES (?,?)",
                        [
                            ("source_root", json.dumps(str(source))),
                            ("library_root", json.dumps(str(managed))),
                        ],
                    )

                self._transaction("更换目标资源库", steps, migrate_settings)
                if not self._data_dir_explicit:
                    self._relocate_data_dir(managed)
                return self.settings()
            self.db.executemany(
                "INSERT OR REPLACE INTO settings VALUES (?,?)",
                [
                    ("source_root", json.dumps(str(source))),
                    ("library_root", json.dumps(str(managed))),
                ],
            )
            self.db.commit()
            if getattr(self, "global_db", None):
                self.global_db.executemany(
                    "INSERT OR REPLACE INTO app_settings VALUES (?,?)",
                    [("last_source_root", json.dumps(str(source))), ("last_library_root", json.dumps(str(managed)))],
                )
                self.global_db.commit()
            if not self._data_dir_explicit:
                self._relocate_data_dir(managed or source)
            return self.settings()

    def _relocate_data_dir(self, root: Path) -> None:
        """Keep the portable app's records beside the selected target library.

        The database/cache are implementation details, so they follow the
        library instead of accumulating under the executable or a user
        profile. An explicitly supplied data_dir remains untouched for tests,
        portable integrations, and advanced deployments.
        """
        if self.data_dir is None:
            self._attach_data_dir(root)
            return
        destination = (Path(root) / ".resource-controller-data").resolve()
        if destination == self.data_dir:
            return
        if destination.exists():
            raise LibraryError(
                f"目标库已存在程序数据目录：{destination}。请先备份或选择其他目标库。"
            )
        old = self.data_dir
        self.db.commit()
        self.db.close()
        try:
            shutil.move(str(old), str(destination))
        except Exception:
            self.db = sqlite3.connect(old / "library.sqlite3", check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            raise
        self.data_dir = destination
        for folder in ("cache", "backups", "trash"):
            (self.data_dir / folder).mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / "library.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")

    def _attach_data_dir(self, root: Path) -> None:
        """Persist an in-memory bootstrap session inside a selected library."""
        destination = (Path(root) / ".resource-controller-data").resolve()
        database = destination / "library.sqlite3"
        if database.exists():
            raise LibraryError(f"目标库已存在程序数据目录：{destination}。请先打开该资源库。")
        settings = self.db.execute("SELECT key,value FROM settings").fetchall()
        self.db.close()
        destination.mkdir(parents=True, exist_ok=True)
        for folder in ("cache", "backups", "trash"):
            (destination / folder).mkdir(exist_ok=True)
        self.data_dir = destination
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        if settings:
            self.db.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", settings)
            self.db.commit()

    def _category(self, value: str) -> str:
        value = str(value).replace("\\", "/").strip("/")
        if not value:
            raise LibraryError("分类名称不能为空。")
        parts = value.split("/")
        for part in parts:
            clean_component(part)
            if "{" in part or "}" in part:
                raise LibraryError("分类名称不能包含大括号；大括号由程序用于标识分类文件夹。")
        return "/".join(parts)

    def _category_path(self, category: str) -> Path:
        if not self.library_root:
            raise LibraryError("请先设置影像目录。")
        category = self._category(category)
        parts = category.split("/")
        marked = self.library_root.joinpath(*(f"{{{part}}}" for part in parts))
        legacy = self.library_root.joinpath(*parts)
        # Existing unmarked categories remain readable, while every newly
        # created category gets an explicit marker that survives a plain
        # folder inspection and can be rediscovered after a database reset.
        path = marked if marked.exists() or not legacy.exists() else legacy
        if not _inside(path, self.library_root):
            raise LibraryError("分类路径超出了分类库目录。")
        return path

    @staticmethod
    def _category_path_at(root: Path, category: str) -> Path:
        parts = str(category).replace("\\", "/").strip("/").split("/")
        marked = root.joinpath(*(f"{{{part}}}" for part in parts))
        legacy = root.joinpath(*parts)
        return marked if marked.exists() or not legacy.exists() else legacy

    @staticmethod
    def _decode_category_dir(name: str) -> str | None:
        match = re.fullmatch(r"\{(.+)\}", name)
        if not match or match.group(1) in {".", ".."}:
            return None
        try:
            return clean_component(match.group(1))
        except LibraryError:
            return None

    def _discover_marked_categories(self) -> list[str]:
        """Discover `{分类}` folders without traversing ordinary folder resources."""
        roots = []
        for root in (self.library_root,):
            if root and root.is_dir():
                roots.append(root)
        discovered: list[str] = []
        for root in roots:
            stack = [(root, "")]
            while stack:
                parent, prefix = stack.pop()
                try:
                    entries = list(os.scandir(parent))
                except OSError:
                    continue
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    name = self._decode_category_dir(entry.name)
                    if name is None:
                        continue
                    path = f"{prefix}/{name}" if prefix else name
                    discovered.append(path)
                    stack.append((Path(entry.path), path))
        return sorted(set(discovered))

    def categories(self) -> list[dict]:
        with self._lock:
            result = []
            for row in self.db.execute("SELECT path FROM categories ORDER BY path COLLATE NOCASE"):
                cat = row[0]
                count = self.db.execute(
                    'SELECT count(*) FROM resources WHERE trashed=0 AND (category=? OR category LIKE ? ESCAPE "\\")',
                    (cat, self._like(cat) + "/%"),
                ).fetchone()[0]
                result.append(
                    {
                        "path": cat,
                        "name": cat.rsplit("/", 1)[-1],
                        "parent": cat.rpartition("/")[0],
                        "count": count,
                    }
                )
            return result

    @staticmethod
    def _like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def tags(self) -> list[dict]:
        with self._lock:
            counts: dict[str, int] = {}
            for row in self.db.execute("SELECT tags FROM resources WHERE trashed=0"):
                for tag in (_json_load(row[0], []) or []):
                    counts[tag] = counts.get(tag, 0) + 1
            local = {
                row[0]
                for row in self.db.execute("SELECT name FROM tags")
            }
            global_names = {
                row[0]
                for row in self.global_db.execute("SELECT name FROM global_tags")
            } if getattr(self, "global_db", None) else set()
            return [
                {"name": row[0], "count": counts.get(row[0], 0)}
                for row in ((name,) for name in sorted(local | global_names, key=str.casefold))
            ]

    def _snapshot(self) -> dict:
        return {
            table: [dict(row) for row in self.db.execute(f"SELECT * FROM {table}")]
            for table in ("settings", "resources", "categories", "tags")
        }

    def _restore(self, snapshot: dict):
        for table in ("settings", "resources", "categories", "tags"):
            # Journals written by earlier releases did not include settings.
            # Preserve current settings when recovering one of those records
            # instead of treating a missing key as an empty table.
            if table not in snapshot:
                continue
            self.db.execute(f"DELETE FROM {table}")
            for row in snapshot[table]:
                keys = list(row)
                self.db.execute(
                    f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                    tuple(row[k] for k in keys),
                )

    def backup(self) -> str:
        with self._lock:
            path = (
                self.data_dir
                / "backups"
                / f"library-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.sqlite3"
            )
            target = sqlite3.connect(path)
            try:
                self.db.backup(target)
            finally:
                target.close()
            return str(path)

    def _move(self, source: str, destination: str):
        src, dst = Path(source), Path(destination)
        if not src.exists():
            raise LibraryError(f"源资源不存在：{src.name}")
        if dst.exists() and _key(src) != _key(dst):
            raise LibraryError(f"目标已存在，未覆盖：{dst.name}")
        if _key(src) == _key(dst):
            if str(src) != str(dst):
                temporary = src.with_name(".resource-controller-" + uuid.uuid4().hex)
                src.rename(temporary)
                try:
                    temporary.rename(dst)
                except Exception:
                    temporary.rename(src)
                    raise
            return
        if not dst.parent.is_dir():
            raise LibraryError("目标目录不存在。")
        shutil.move(str(src), str(dst))

    def _copy(self, source: str, destination: str):
        """Copy one atomic resource without touching the source."""
        src, dst = Path(source), Path(destination)
        if not src.exists():
            raise LibraryError(f"源资源不存在：{src.name}")
        if dst.exists():
            raise LibraryError(f"目标已存在，未覆盖：{dst.name}")
        if not dst.parent.is_dir():
            raise LibraryError("目标目录不存在。")
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    def _run_step(self, step: dict, reverse: bool = False):
        if step["action"] == "move":
            self._move(
                step["to"] if reverse else step["from"], step["from"] if reverse else step["to"]
            )
        elif step["action"] == "mkdir":
            if reverse:
                Path(step["path"]).rmdir()
            else:
                Path(step["path"]).mkdir()
        elif step["action"] == "copy":
            if reverse:
                # A failed or undone copy is moved into internal trash so no
                # user-created bytes are silently deleted.
                source = Path(step["to"])
                if not source.exists():
                    raise LibraryError(f"复制目标不存在：{source.name}")
                trash = Path(
                    step.get("undo_to")
                    or (self.data_dir / "trash" / (uuid.uuid4().hex + "__" + source.name))
                )
                self._move(str(source), str(trash))
            else:
                self._copy(step["from"], step["to"])

    def _transaction(self, title: str, steps: list[dict], mutate) -> dict:
        """Journal intent before touching media; compensate on any failure."""
        self._assert_healthy()
        before = self._snapshot()
        operation_id = uuid.uuid4().hex
        if len(steps) >= 20:
            self.backup()
        payload = {"steps": steps, "completed": 0, "before": before}
        self.db.execute(
            "INSERT INTO operations VALUES (?,?,?,?,?,NULL)",
            (operation_id, title, time.time(), "pending", json.dumps(payload, ensure_ascii=False)),
        )
        self.db.commit()
        completed = []
        try:
            for step in steps:
                self._run_step(step)
                completed.append(step)
                payload["completed"] = len(completed)
                self.db.execute(
                    "UPDATE operations SET payload=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), operation_id),
                )
                self.db.commit()
            mutate()
            payload["after"] = self._snapshot()
            # ``steps`` only describes filesystem work.  Metadata-only
            # operations (grade/tag/cover changes) legitimately have no
            # move/mkdir steps, but the operation log must still report how
            # many records were affected.  Prefer changed resources, then
            # taxonomy rows, and finally filesystem steps for legacy callers.
            changed_counts = {}
            for table, primary in (
                ("settings", "key"),
                ("resources", "id"),
                ("categories", "path"),
                ("tags", "name"),
            ):
                before_rows = {row[primary]: row for row in before[table]}
                after_rows = {row[primary]: row for row in payload["after"][table]}
                changed_counts[table] = sum(
                    before_rows.get(key) != after_rows.get(key)
                    for key in before_rows.keys() | after_rows.keys()
                )
            payload["count"] = (
                changed_counts["resources"]
                or changed_counts["categories"]
                or changed_counts["tags"]
                or changed_counts["settings"]
                or len(steps)
            )
            self.db.execute(
                "UPDATE operations SET status=?,payload=? WHERE id=?",
                ("done", json.dumps(payload, ensure_ascii=False), operation_id),
            )
            self.db.commit()
            if getattr(self, "global_db", None):
                try:
                    self.global_db.execute(
                        "INSERT OR REPLACE INTO global_operations(id,title,created,count,status,library_root) VALUES (?,?,?,?,?,?)",
                        (operation_id, title, time.time(), int(payload.get("count", 0)), "done", str(self.library_root or "")),
                    )
                    self.global_db.commit()
                except sqlite3.Error:
                    # A locked or read-only global history database must not
                    # make an already committed resource operation appear to
                    # have failed.
                    pass
            # Return the same affected-record count that is persisted in the
            # operation payload.  Metadata-only operations (for example
            # creating a tag or changing a cover) have no filesystem steps,
            # so ``len(steps)`` would incorrectly report zero to API callers.
            return {"operation_id": operation_id, "title": title, "count": payload["count"]}
        except Exception as exc:
            self.db.rollback()
            rollback_errors = []
            for step in reversed(completed):
                try:
                    self._run_step(step, reverse=True)
                except Exception as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            self._restore(before)
            error = str(exc) + (
                "；回滚未完成：" + "; ".join(rollback_errors) if rollback_errors else ""
            )
            self.db.execute(
                "UPDATE operations SET status=?,error=? WHERE id=?",
                ("recovery_required" if rollback_errors else "failed", error, operation_id),
            )
            self.db.commit()
            raise LibraryError(error) from exc

    def _assert_healthy(self):
        if self.db.execute(
            "SELECT 1 FROM operations WHERE status='recovery_required' LIMIT 1"
        ).fetchone():
            raise LibraryError(
                "存在未完成的文件恢复，请先查看操作日志并恢复冲突路径，暂停进一步文件变更。"
            )

    def _recover(self):
        # A crash can happen between a filesystem move and its journal update.
        # Existing source/destination states are inspected; never overwrite.
        for row in self.db.execute("SELECT * FROM operations WHERE status='pending'").fetchall():
            payload = _json_load(row["payload"], {}) or {}
            errors = []
            for step in reversed(payload["steps"]):
                try:
                    if step["action"] == "move":
                        src, dst = Path(step["from"]), Path(step["to"])
                        if dst.exists() and not src.exists():
                            self._run_step(step, reverse=True)
                        elif dst.exists() and src.exists() and _key(src) != _key(dst):
                            errors.append(f"恢复冲突：{src} / {dst}")
                    elif step["action"] == "copy":
                        dst = Path(step["to"])
                        if dst.exists():
                            self._run_step(step, reverse=True)
                    elif Path(step["path"]).exists():
                        Path(step["path"]).rmdir()
                except Exception as exc:
                    errors.append(str(exc))
            self._restore(payload["before"])
            self.db.execute(
                "UPDATE operations SET status=?,error=? WHERE id=?",
                ("recovery_required" if errors else "recovered", "; ".join(errors), row["id"]),
            )
            self.db.commit()

    def scan(self) -> dict:
        with self._lock:
            self._assert_healthy()
            if not self.source_root:
                raise LibraryError("请先选择原始目录。")
            discovered = self._discover_marked_categories()
            if discovered:
                self.db.executemany(
                    "INSERT OR IGNORE INTO categories VALUES (?)",
                    [(category,) for category in discovered],
                )
                self.db.commit()
            categories = [r[0] for r in self.db.execute("SELECT path FROM categories")]
            category_paths = {_key(self._category_path(c)) for c in categories}
            directories: dict[str, tuple[Path, str | None]] = {
                _key(self.source_root): (self.source_root, None)
            }
            if self.library_root and self.library_root != self.source_root:
                directories[_key(self.library_root)] = (self.library_root, "")
            for category in categories:
                path = self._category_path(category)
                directories[_key(path)] = (path, category)
            existing = [dict(r) for r in self.db.execute("SELECT * FROM resources WHERE trashed=0")]
            by_path = {_key(r["path"]): r for r in existing}
            fingerprints: dict[str, list[dict]] = {}
            for row in existing:
                fingerprints.setdefault(row["fingerprint"], []).append(row)
            found_ids, errors = set(), []
            scanned_directories = set()
            for directory, category in directories.values():
                try:
                    entries = list(os.scandir(directory))
                except OSError as exc:
                    errors.append(f"{directory}: {exc}")
                    continue
                scanned_directories.add(_key(directory))
                for entry in entries:
                    try:
                        path = Path(entry.path)
                        if (
                            entry.is_symlink()
                            or (hasattr(path, "is_junction") and path.is_junction())
                            or path.name.startswith(".resource-controller-")
                            or _key(path) in category_paths
                            or _key(path) == _key(self.data_dir)
                        ):
                            continue
                        if (
                            self.library_root
                            and self.library_root != self.source_root
                            and _key(path) == _key(self.library_root)
                        ):
                            continue
                        if _key(path) == _key(self.source_root):
                            continue
                        folder = entry.is_dir(follow_symlinks=False)
                        suffix = path.suffix.lower()
                        typ = (
                            "folder"
                            if folder
                            else "image"
                            if suffix in IMAGE_EXTENSIONS
                            else "video"
                            if suffix in VIDEO_EXTENSIONS
                            else None
                        )
                        if not typ:
                            continue
                        st = entry.stat(follow_symlinks=False)
                        fingerprint = f"{st.st_dev}:{st.st_ino}" if st.st_ino else ""
                        old = by_path.get(_key(path))
                        matches = fingerprints.get(fingerprint, []) if fingerprint else []
                        if (
                            old is None
                            and len(matches) == 1
                            and not Path(matches[0]["path"]).exists()
                            and matches[0]["id"] not in found_ids
                        ):
                            old = matches[0]
                        grade, name, tags, extension = parse_name(path.name, folder)
                        resource_id = old["id"] if old else uuid.uuid4().hex
                        found_ids.add(resource_id)
                        self.db.execute(
                            """INSERT INTO resources(id,path,name,grade,tags,category,type,extension,size,mtime,fingerprint,cover)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                            path=excluded.path,name=excluded.name,grade=excluded.grade,tags=excluded.tags,
                            category=excluded.category,type=excluded.type,extension=excluded.extension,
                            size=excluded.size,mtime=excluded.mtime,fingerprint=excluded.fingerprint""",
                            (
                                resource_id,
                                str(path),
                                name,
                                grade,
                                json.dumps(tags, ensure_ascii=False),
                                category,
                                typ,
                                extension,
                                0 if folder else st.st_size,
                                st.st_mtime,
                                fingerprint,
                                old["cover"] if old else None,
                            ),
                        )
                        self.db.executemany(
                            "INSERT OR IGNORE INTO tags VALUES (?)", [(tag,) for tag in tags]
                        )
                    except OSError as exc:
                        errors.append(f"{entry.name}: {exc}")
            for row in existing:
                if Path(row["path"]).name.startswith(".resource-controller-"):
                    self.db.execute("DELETE FROM resources WHERE id=?", (row["id"],))
                    continue
                if (
                    row["id"] not in found_ids
                    and _key(Path(row["path"]).parent) in scanned_directories
                    and not Path(row["path"]).exists()
                ):
                    self.db.execute("DELETE FROM resources WHERE id=?", (row["id"],))
            self.db.commit()
            if getattr(self, "global_db", None):
                names = {tag for row in self.db.execute("SELECT tags FROM resources") for tag in (_json_load(row[0], []) or [])}
                self.global_db.executemany("INSERT OR IGNORE INTO global_tags VALUES (?)", [(name,) for name in names])
                self.global_db.commit()
            return {"count": len(found_ids), "errors": errors}

    @staticmethod
    def _resource(row) -> dict:
        result = dict(row)
        result["tags"] = _json_load(result.get("tags"), []) or []
        result["trashed"] = bool(result["trashed"])
        return result

    def get(self, resource_id: str) -> dict:
        with self._lock:
            row = self.db.execute("SELECT * FROM resources WHERE id=?", (resource_id,)).fetchone()
            if not row:
                raise LibraryError("资源不存在，请重新同步。")
            return self._resource(row)

    def resources(
        self,
        category: str | None = None,
        grade: str = "",
        tags: list[str] | None = None,
        type: str = "",
        query: str = "",
        recursive: bool = True,
        view: str = "all",
    ) -> list[dict]:
        """category=None: all; category='': inbox. Selected tags use AND."""
        with self._lock:
            result = []
            for row in self.db.execute(
                "SELECT * FROM resources ORDER BY name COLLATE NOCASE, path"
            ):
                resource = self._resource(row)
                if Path(resource["path"]).name.startswith(".resource-controller-"):
                    continue
                if resource["trashed"] != (view == "trash"):
                    continue
                cat = resource["category"] or ""
                if (view == "inbox" or category == "") and cat:
                    continue
                if category and not (
                    cat == category or (recursive and cat.startswith(category + "/"))
                ):
                    continue
                if grade and resource["grade"] != grade:
                    continue
                if type and resource["type"] != type:
                    continue
                if tags and not set(tags).intersection(resource["tags"]):
                    continue
                if (
                    query.casefold()
                    not in (" ".join([resource["name"], cat, *resource["tags"]])).casefold()
                ):
                    continue
                result.append(resource)
            return result

    def stats(self, category: str | None = None, view: str = "all") -> dict:
        """Return counts for the current browsing scope."""
        rows = self.resources(category=category, view=view)
        return {
            "total": len(rows),
            "inbox": sum(not r["category"] for r in self.resources(view="inbox")),
            "images": sum(r["type"] == "image" for r in rows),
            "videos": sum(r["type"] == "video" for r in rows),
            "folders": sum(r["type"] == "folder" for r in rows),
            "trash": len(self.resources(view="trash")),
            "size": sum(r["size"] for r in rows),
            "categories": len(self.categories()),
            "tags": len(self.tags()),
            "grades": {g: sum(r["grade"] == g for r in rows) for g in ("A", "B", "C")},
        }

    def create_category(self, path: str, preview: bool = False) -> dict:
        with self._lock:
            path = self._category(path)
            known = {r[0] for r in self.db.execute("SELECT path FROM categories")}
            parts = path.split("/")
            additions, steps = [], []
            for index in range(1, len(parts) + 1):
                category = "/".join(parts[:index])
                if category in known:
                    continue
                parent = category.rpartition("/")[0]
                dest = self._category_path(category)
                if dest.exists():
                    raise LibraryError("同名文件夹已存在，可能是原子资源；请选择其他分类名称。")
                additions.append(category)
                steps.append({"action": "mkdir", "path": str(dest)})
            if preview:
                return {"changes": steps, "count": len(steps)}
            if not additions:
                return {"count": 0}
            return self._transaction(
                "创建分类",
                steps,
                lambda: self.db.executemany(
                    "INSERT INTO categories VALUES (?)", [(c,) for c in additions]
                ),
            )

    def _selection(self, ids: list[str]) -> list[dict]:
        if not ids:
            raise LibraryError("请先选择资源。")
        return [self.get(resource_id) for resource_id in dict.fromkeys(ids)]

    def batch_update(
        self,
        ids: list[str],
        *,
        grade: str | None = None,
        name: str | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        tags: list[str] | None = None,
        category: str | None = None,
        trash: bool = False,
        preview: bool = False,
    ) -> dict:
        """Use preview=True to inspect changes, then repeat with preview=False.

        name supports {name} and {n}; n starts at one. category='' means inbox.
        Omit category to keep the existing category. Folders remain atomic.
        """
        with self._lock:
            selected = self._selection(ids)
            changes, rows, destinations = [], [], set()
            for index, resource in enumerate(selected, 1):
                if resource["trashed"]:
                    raise LibraryError("待删区资源请通过撤销淘汰操作恢复。")
                updated = dict(resource)
                if grade is not None:
                    updated["grade"] = grade
                if name is not None:
                    updated["name"] = (
                        str(name).replace("{name}", resource["name"]).replace("{n}", str(index))
                    )
                raw_tags = tags if tags is not None else resource["tags"]
                updated["tags"] = list(
                    dict.fromkeys(clean_component(tag, tag=True) for tag in raw_tags)
                )
                for tag in add_tags or []:
                    tag = clean_component(tag, tag=True)
                    if tag not in updated["tags"]:
                        updated["tags"].append(tag)
                remove = {
                    clean_component(tag, tag=True) for tag in (remove_tags or [])
                }
                updated["tags"] = [t for t in updated["tags"] if t not in remove]
                normalized_category = ""
                if category is not None:
                    # Normalize the public category input once and persist the
                    # canonical slash separated value.  Callers may pass a
                    # Windows style path (``foo\\bar``); storing it verbatim
                    # would make the resource invisible to category queries
                    # and could point the move at a different directory.
                    normalized_category = self._category(category) if category else ""
                    if (
                        normalized_category
                        and not self.db.execute(
                            "SELECT 1 FROM categories WHERE path=?", (normalized_category,)
                        ).fetchone()
                    ):
                        raise LibraryError("目标分类不存在，请先创建分类。")
                    updated["category"] = normalized_category or None
                parent = Path(resource["path"]).parent
                if category is not None:
                    parent = (
                        self._category_path(normalized_category)
                        if normalized_category
                        else self.source_root
                    )
                if parent is None:
                    raise LibraryError("尚未设置原始目录。")
                filename = build_name(
                    updated["name"], updated["grade"], updated["tags"], updated["extension"]
                )
                if trash:
                    parent = self.data_dir / "trash"
                    filename = resource["id"] + "__" + Path(resource["path"]).name[:180]
                    updated["trashed"] = True
                destination = parent / filename
                if resource["type"] == "folder" and _inside(parent, Path(resource["path"])):
                    raise LibraryError("不能将文件夹资源移动到自身内部。")
                dest_key = _key(destination)
                if dest_key in destinations:
                    raise LibraryError("批次内存在重名，请使用 {n} 编号区分。")
                destinations.add(dest_key)
                if destination.exists() and dest_key != _key(resource["path"]):
                    raise LibraryError(f"目标已存在，未覆盖：{destination.name}")
                updated["path"] = str(destination)
                if str(destination) != resource["path"]:
                    changes.append(
                        {
                            "action": "move",
                            "from": resource["path"],
                            "to": str(destination),
                            "id": resource["id"],
                        }
                    )
                rows.append(updated)
            if preview:
                return {"changes": changes, "resources": rows, "count": len(rows)}

            def mutate():
                for resource in rows:
                    self.db.execute(
                        "UPDATE resources SET path=?,name=?,grade=?,tags=?,category=?,trashed=? WHERE id=?",
                        (
                            resource["path"],
                            resource["name"],
                            resource["grade"],
                            json.dumps(resource["tags"], ensure_ascii=False),
                            resource["category"],
                            int(resource["trashed"]),
                            resource["id"],
                        ),
                    )
                    self.db.executemany(
                        "INSERT OR IGNORE INTO tags VALUES (?)", [(t,) for t in resource["tags"]]
                    )

            result = self._transaction("移至待删区" if trash else "批量更新资源", changes, mutate)
            result["resources"] = rows
            return result

    def copy_resources(
        self,
        ids: list[str],
        category: str | None = None,
        *,
        preview: bool = False,
    ) -> dict:
        """Copy selected atomic resources into a user-created category and journal it.

        Sources remain untouched. The copies receive new resource IDs and are
        ordinary indexed resources. ``category=None`` is rejected to avoid an
        accidental same-directory collision; pass ``category=''`` for inbox.
        Undo moves copied resources to the internal trash and removes their
        index rows, preserving the original sources.
        """
        with self._lock:
            if category is None:
                raise LibraryError("复制必须指定目标分类；使用空字符串复制到收件箱。")
            selected = self._selection(ids)
            normalized = self._category(category) if category else ""
            if normalized:
                if not self.db.execute("SELECT 1 FROM categories WHERE path=?", (normalized,)).fetchone():
                    raise LibraryError("目标分类不存在，请先创建分类。")
                destination_dir = self._category_path(normalized)
            else:
                if self.source_root is None:
                    raise LibraryError("尚未设置原始目录。")
                destination_dir = self.source_root
            steps, rows, destinations = [], [], set()
            for resource in selected:
                if resource["trashed"]:
                    raise LibraryError("待删区资源不能复制。")
                destination = destination_dir / Path(resource["path"]).name
                if _key(destination) in destinations or destination.exists():
                    raise LibraryError(f"目标已存在，未覆盖：{destination.name}")
                destinations.add(_key(destination))
                new_id = uuid.uuid4().hex
                copied = dict(resource)
                copied.update({"id": new_id, "path": str(destination), "category": normalized or None, "trashed": False})
                # A folder cover is relative to the copied folder and remains
                # valid after copytree; an external video poster is shared.
                steps.append({"action": "copy", "from": resource["path"], "to": str(destination), "id": new_id})
                rows.append(copied)
            if preview:
                return {"changes": steps, "resources": rows, "count": len(rows)}

            def mutate():
                for resource in rows:
                    stat = Path(resource["path"]).stat()
                    fingerprint = f"{stat.st_dev}:{stat.st_ino}" if stat.st_ino else ""
                    self.db.execute(
                        """INSERT INTO resources
                        (id,path,name,grade,tags,category,type,extension,size,mtime,trashed,cover,fingerprint,hash,hash_signature)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (resource["id"], resource["path"], resource["name"], resource["grade"],
                         json.dumps(resource["tags"], ensure_ascii=False), resource["category"], resource["type"],
                         resource["extension"], 0 if resource["type"] == "folder" else stat.st_size,
                         stat.st_mtime, 0, resource.get("cover"), fingerprint, None, None),
                    )
                    self.db.executemany("INSERT OR IGNORE INTO tags VALUES (?)", [(tag,) for tag in resource["tags"]])

            result = self._transaction("复制资源", steps, mutate)
            result["resources"] = rows
            return result

    def add_tag(self, name: str) -> dict:
        with self._lock:
            name = clean_component(name, tag=True)
            result = self._transaction(
                "新增标签",
                [],
                lambda: self.db.execute("INSERT OR IGNORE INTO tags VALUES (?)", (name,)),
            )
            try:
                self.global_db.execute("INSERT OR IGNORE INTO global_tags VALUES (?)", (name,))
                self.global_db.commit()
            except sqlite3.Error:
                pass
            return result

    def change_tag(self, old: str, new: str | None = None, preview: bool = False) -> dict:
        """Rename/merge a global tag, or delete it with new=None."""
        with self._lock:
            old = clean_component(old, tag=True)
            local_exists = self.db.execute("SELECT 1 FROM tags WHERE name=?", (old,)).fetchone()
            global_exists = self.global_db.execute("SELECT 1 FROM global_tags WHERE name=?", (old,)).fetchone()
            if not local_exists and not global_exists:
                raise LibraryError("标签不存在。")
            if new is not None:
                new = clean_component(new, tag=True)
            selected = [r for r in self.resources() if old in r["tags"]]
            plans, rows = [], []
            for resource in selected:
                next_tags = list(
                    dict.fromkeys(
                        new if t == old and new else t for t in resource["tags"] if t != old or new
                    )
                )
                plan = self.batch_update([resource["id"]], tags=next_tags, preview=True)
                plans.extend(plan["changes"])
                rows.extend(plan["resources"])
            targets = [_key(plan["to"]) for plan in plans]
            if len(targets) != len(set(targets)):
                raise LibraryError("标签变更会生成相同文件名，请先重命名冲突资源。")
            if preview:
                return {"changes": plans, "count": len(rows)}

            def mutate():
                for resource in rows:
                    self.db.execute(
                        "UPDATE resources SET path=?,tags=? WHERE id=?",
                        (
                            resource["path"],
                            json.dumps(resource["tags"], ensure_ascii=False),
                            resource["id"],
                        ),
                    )
                self.db.execute("DELETE FROM tags WHERE name=?", (old,))
                if new:
                    self.db.execute("INSERT OR IGNORE INTO tags VALUES (?)", (new,))

            result = self._transaction(
                "删除标签" if new is None else "重命名或合并标签", plans, mutate
            )
            try:
                self.global_db.execute("DELETE FROM global_tags WHERE name=?", (old,))
                if new:
                    self.global_db.execute("INSERT OR IGNORE INTO global_tags VALUES (?)", (new,))
                self.global_db.commit()
            except sqlite3.Error:
                pass
            return result

    def rename_category(self, old: str, new: str, preview: bool = False) -> dict:
        with self._lock:
            old, new = self._category(old), self._category(new)
            cats = [r[0] for r in self.db.execute("SELECT path FROM categories")]
            if old not in cats:
                raise LibraryError("分类不存在。")
            if new == old:
                return {"count": 0, "changes": []}
            if new.startswith(old + "/"):
                raise LibraryError("不能将分类移动到自身子分类中。")
            # A category rename moves the complete subtree.  Reject a target
            # whose existing descendants belong to another branch; updating
            # the rows one by one would otherwise violate the UNIQUE(path)
            # constraint halfway through the transaction and leave a confusing
            # recovery entry for an operation that could have been validated.
            conflicting = [
                cat
                for cat in cats
                if (cat == new or cat.startswith(new + "/"))
                and not (cat == old or cat.startswith(old + "/"))
            ]
            if conflicting:
                raise LibraryError("目标分类已存在子分类，请选择其他名称。")
            parent = new.rpartition("/")[0]
            if parent and parent not in cats:
                raise LibraryError("目标父分类不存在。")
            destination = self._category_path(new)
            if destination.exists():
                raise LibraryError("目标分类路径已存在。")
            source = self._category_path(old)
            steps = [{"action": "move", "from": str(source), "to": str(destination)}]
            if preview:
                return {"changes": steps, "count": 1}

            def mutate():
                for cat in cats:
                    if cat == old or cat.startswith(old + "/"):
                        self.db.execute(
                            "UPDATE categories SET path=? WHERE path=?",
                            (new + cat[len(old) :], cat),
                        )
                # Include trashed rows in the taxonomy update so restoring a
                # previously discarded resource after a category rename does
                # not resurrect a stale category reference.  Trashed media is
                # kept in the internal trash directory and must not be moved
                # back into the live category while renaming.
                for row in self.db.execute(
                    "SELECT id,path,category,trashed FROM resources WHERE category=? OR category LIKE ? ESCAPE '\\'",
                    (old, self._like(old) + "/%"),
                ).fetchall():
                    cat = row["category"] or ""
                    next_category = new + cat[len(old) :]
                    if row["trashed"]:
                        self.db.execute(
                            "UPDATE resources SET category=? WHERE id=?",
                            (next_category, row["id"]),
                        )
                    else:
                        rel = Path(row["path"]).relative_to(source)
                        self.db.execute(
                            "UPDATE resources SET category=?,path=? WHERE id=?",
                            (next_category, str(destination / rel), row["id"]),
                        )

            return self._transaction("重命名分类", steps, mutate)

    def delete_category(self, category: str, preview: bool = False) -> dict:
        """Move an entire category subtree to trash; no files are deleted."""
        with self._lock:
            category = self._category(category)
            cats = [r[0] for r in self.db.execute("SELECT path FROM categories")]
            affected = [c for c in cats if c == category or c.startswith(category + "/")]
            if not affected:
                raise LibraryError("分类不存在。")
            source = self._category_path(category)
            destination = self.data_dir / "trash" / (uuid.uuid4().hex + "__" + source.name)
            steps = [{"action": "move", "from": str(source), "to": str(destination)}]
            if preview:
                return {"changes": steps, "count": len(self.resources(category=category))}

            def mutate():
                for resource in self.resources(category=category):
                    rel = Path(resource["path"]).relative_to(source)
                    self.db.execute(
                        "UPDATE resources SET path=?,trashed=1 WHERE id=?",
                        (str(destination / rel), resource["id"]),
                    )
                self.db.executemany("DELETE FROM categories WHERE path=?", [(c,) for c in affected])

            return self._transaction("分类移至待删区", steps, mutate)

    def set_cover(self, resource_id: str, image_path: str | None) -> dict:
        with self._lock:
            resource = self.get(resource_id)
            if resource["type"] != "folder":
                raise LibraryError("只有文件夹资源可引用内部图片作为封面。")
            cover = None
            if image_path:
                path = Path(image_path).resolve()
                root = Path(resource["path"]).resolve()
                if (
                    not _inside(path, root)
                    or not path.is_file()
                    or path.suffix.lower() not in IMAGE_EXTENSIONS
                ):
                    raise LibraryError("请选择此文件夹资源内部的一张图片。")
                cover = str(path.relative_to(root))
            return self._transaction(
                "设置文件夹封面",
                [],
                lambda: self.db.execute(
                    "UPDATE resources SET cover=? WHERE id=?", (cover, resource_id)
                ),
            )

    def set_video_cover(self, resource_id: str, image_path: str | None) -> dict:
        """Store a program-only video poster path; never touches the video file."""
        with self._lock:
            resource = self.get(resource_id)
            if resource["type"] != "video":
                raise LibraryError("只有视频资源可以设置视频封面。")
            cover = None
            if image_path:
                path = Path(image_path).expanduser().resolve()
                if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                    raise LibraryError("视频封面必须是已生成的图片文件。")
                cover = str(path)
            return self._transaction(
                "设置视频封面",
                [],
                lambda: self.db.execute(
                    "UPDATE resources SET cover=? WHERE id=?", (cover, resource_id)
                ),
            )

    def cover_path(self, resource_id: str) -> str | None:
        resource = self.get(resource_id)
        if resource["type"] == "image":
            return resource["path"]
        if resource["type"] == "folder" and resource["cover"]:
            path = Path(resource["path"]) / resource["cover"]
            if _inside(path, Path(resource["path"])) and path.is_file():
                return str(path)
        if resource["type"] == "video" and resource["cover"]:
            path = Path(resource["cover"])
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                return str(path)
        return None

    def logs(self, limit: int = 100) -> list[dict]:
        with self._lock:
            result = []
            for row in self.db.execute(
                "SELECT * FROM operations ORDER BY created DESC LIMIT ?",
                (min(max(int(limit), 1), 1000),),
            ):
                data = dict(row)
                payload = _json_load(data.pop("payload"), {}) or {}
                data["count"] = payload.get("count", len(payload.get("steps", [])))
                data["changes"] = payload.get("steps", [])
                result.append(data)
            if getattr(self, "global_db", None):
                seen = {row["id"] for row in result}
                for row in self.global_db.execute(
                    "SELECT * FROM global_operations ORDER BY created DESC LIMIT ?",
                    (min(max(int(limit), 1), 1000),),
                ):
                    if row["id"] in seen:
                        continue
                    result.append({
                        "id": row["id"], "title": row["title"], "created": row["created"],
                        "count": row["count"], "status": "global", "changes": [],
                    })
                result.sort(key=lambda item: item["created"], reverse=True)
                result = result[: min(max(int(limit), 1), 1000)]
            return result

    def undo(self, operation_id: str | None = None, preview: bool = False) -> dict:
        with self._lock:
            row = (
                self.db.execute(
                    "SELECT * FROM operations WHERE id=? AND status='done'", (operation_id,)
                ).fetchone()
                if operation_id
                else self.db.execute(
                    "SELECT * FROM operations WHERE status='done' ORDER BY created DESC LIMIT 1"
                ).fetchone()
            )
            if not row:
                raise LibraryError("没有可撤销的操作。")
            payload = _json_load(row["payload"], {}) or {}
            current, replacements = self._snapshot(), {}
            for table, primary in (
                ("settings", "key"),
                ("resources", "id"),
                ("categories", "path"),
                ("tags", "name"),
            ):
                # Compatibility with operation payloads created before
                # settings were captured in transaction snapshots.
                if table not in payload["before"] or table not in payload["after"]:
                    replacements[table] = list(current[table])
                    continue
                before = {r[primary]: r for r in payload["before"][table]}
                after = {r[primary]: r for r in payload["after"][table]}
                now = {r[primary]: r for r in current[table]}
                changed = {
                    key for key in before.keys() | after.keys() if before.get(key) != after.get(key)
                }

                def comparable(value):
                    if not value:
                        return value
                    return {
                        k: v
                        for k, v in value.items()
                        if k not in {"mtime", "size", "fingerprint", "hash", "hash_signature"}
                    }

                for key in changed:
                    if comparable(now.get(key)) != comparable(after.get(key)):
                        raise LibraryError("此批次的资源已被后续操作修改，请先撤销相关后续操作。")
                    if key in before:
                        restored = dict(before[key])
                        if table == "resources" and key in now:
                            for field in ("size", "mtime", "fingerprint", "hash", "hash_signature"):
                                restored[field] = now[key][field]
                        now[key] = restored
                    else:
                        now.pop(key, None)
                replacements[table] = list(now.values())
            restored_tags = {r["name"] for r in replacements["tags"]}
            for resource in replacements["resources"]:
                if not resource["trashed"] and not set(_json_load(resource["tags"], []) or []).issubset(
                    restored_tags
                ):
                    raise LibraryError("此标签已被其他资源使用，请先撤销相关后续操作。")
            reverse_steps = []
            for step in reversed(payload["steps"]):
                if step["action"] == "move":
                    dst, src = Path(step["from"]), Path(step["to"])
                    if not src.exists() or (dst.exists() and _key(src) != _key(dst)):
                        raise LibraryError("撤销路径冲突或资源已从外部移动，未覆盖现有文件。")
                    reverse_steps.append({"action": "move", "from": str(src), "to": str(dst)})
                elif step["action"] == "copy":
                    src = Path(step["to"])
                    if not src.exists():
                        raise LibraryError("撤销复制失败：复制目标已从外部删除或移动。")
                    trash = self.data_dir / "trash" / (uuid.uuid4().hex + "__" + src.name)
                    reverse_steps.append({"action": "move", "from": str(src), "to": str(trash)})
                else:
                    # Empty category creation can be undone without deleting
                    # externally added contents: preserve its directory in trash.
                    src = Path(step["path"])
                    if src.exists():
                        known_descendants = {
                            Path(s["path"]) for s in payload["steps"] if s["action"] == "mkdir"
                        }
                        # A replacement may create a new category and move
                        # imported resources into it in the same transaction.
                        # Those destination files are expected to leave again
                        # during undo; only unrelated user content blocks the
                        # reversible removal of the directory.
                        allowed = set(known_descendants)
                        for move in payload["steps"]:
                            if move.get("action") != "move":
                                continue
                            destination = Path(move["to"])
                            try:
                                destination.relative_to(src)
                            except ValueError:
                                continue
                            allowed.add(destination)
                            while destination != src:
                                destination = destination.parent
                                allowed.add(destination)
                        if any(p not in allowed for p in src.iterdir()):
                            raise LibraryError("分类中已有内容，请先移出资源后撤销创建。")
                        reverse_steps.append(
                            {
                                "action": "move",
                                "from": str(src),
                                "to": str(
                                    self.data_dir / "trash" / (uuid.uuid4().hex + "__" + src.name)
                                ),
                            }
                        )
            if preview:
                return {
                    "changes": reverse_steps,
                    "count": len(reverse_steps),
                    "title": row["title"],
                }
            result = self._transaction(
                "撤销：" + row["title"], reverse_steps, lambda: self._restore(replacements)
            )
            self.db.execute("UPDATE operations SET status='undone' WHERE id=?", (row["id"],))
            self.db.execute(
                "UPDATE operations SET status='undo' WHERE id=?", (result["operation_id"],)
            )
            self.db.commit()
            return result

    @staticmethod
    def _video_hashes(
        path: str, ffmpeg: str | None = None
    ) -> list[tuple[int, tuple[int, int, int]]]:
        """Create perceptual hashes for three representative video frames.

        Frames are streamed through FFmpeg and never written beside the source
        file. A missing/unsupported frame simply reduces the sample count.
        """
        executable = resolve_ffmpeg(ffmpeg)
        if not executable:
            raise LibraryError("相似视频检测需要 FFmpeg。请运行 install_runtime.ps1。")
        try:
            from PIL import Image
        except ImportError as exc:
            raise LibraryError("相似视频检测需要安装 Pillow。") from exc
        # Use evenly spaced timestamps. This is robust for different durations
        # and avoids relying on container-specific keyframe metadata.
        duration = 0.0
        try:
            probe = subprocess.run(
                [executable, "-hide_banner", "-i", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            report = probe.stderr or probe.stdout
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", report)
            if match:
                duration = (
                    int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
                )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if duration:
            points = [duration * ratio for ratio in (0.2, 0.5, 0.8)]
        else:
            # Unknown duration: the old 0/1/2 fallback often decoded only one
            # frame for short clips and yielded unsafe similarity matches.
            points = [0.0, 0.35]
        points = list(dict.fromkeys(round(max(0.0, point), 3) for point in points))
        hashes = []
        for point in points:
            try:
                process = subprocess.run(
                    [
                        executable,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-ss",
                        f"{point:g}",
                        "-i",
                        path,
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=9:8:force_original_aspect_ratio=decrease",
                        "-f",
                        "image2pipe",
                        "-vcodec",
                        "png",
                        "pipe:1",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                    timeout=20,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if process.returncode != 0 or not process.stdout:
                    continue
                with Image.open(io.BytesIO(process.stdout)) as image:
                    pixels = _pixel_values(image.convert("L").resize((9, 8)))
                    color = image.convert("RGB").resize((1, 1)).getpixel((0, 0))
                digest = sum(
                    (pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
                    for y in range(8)
                    for x in range(8)
                )
                hashes.append((digest, color))
            except Exception:
                continue
        # One representative frame is insufficient evidence for a video.
        return hashes if len(hashes) >= 2 else []

    def duplicates(
        self,
        mode: str = "exact",
        category: str | None = None,
        ids: list[str] | None = None,
        compare_all: bool = False,
        source_ids: list[str] | None = None,
        threshold: int = 8,
        expand_folder: str | Path | None = None,
    ) -> dict:
        """Find duplicate candidates without moving/deleting media.

        When ``compare_all`` is enabled, ``source_ids`` identifies the
        resources that started the search (for example, the inbox). All
        non-trash resources are used as comparison candidates, but returned
        groups must contain at least one source resource.
        """
        if mode not in {"exact", "similar"}:
            raise LibraryError("未知去重模式。")
        source_set = set(source_ids or ids or [])
        candidate_scope = self.resources() if compare_all else self.resources(category=category)
        resources = [
            r for r in candidate_scope
            if r["type"] != "folder" and (compare_all or ids is None or r["id"] in ids)
        ]
        temporary_scope = None
        if expand_folder is not None:
            folder = Path(expand_folder).expanduser().resolve()
            owner = next((r for r in (self.resources() if compare_all else self.resources(category=category))
                          if r["type"] == "folder" and _key(r["path"]) == _key(folder)), None)
            if owner is None or not folder.is_dir():
                raise LibraryError("高级展开只允许选择一个已索引的文件夹资源。")
            temporary_scope, resources = str(folder), []
            try:
                for root, dirs, files in os.walk(folder, topdown=True, followlinks=False):
                    dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
                    for filename in files:
                        path = Path(root) / filename
                        if path.is_symlink():
                            continue
                        suffix = path.suffix.lower()
                        typ = "image" if suffix in IMAGE_EXTENSIONS else "video" if suffix in VIDEO_EXTENSIONS else None
                        if not typ:
                            continue
                        try:
                            stat = path.stat()
                        except OSError:
                            continue
                        resources.append({"id": "temporary:" + uuid.uuid4().hex, "path": str(path),
                                          "name": path.name, "grade": "", "tags": [],
                                          "category": owner["category"], "type": typ,
                                          "extension": path.suffix, "size": stat.st_size,
                                          "mtime": stat.st_mtime, "trashed": False,
                                          "cover": None, "hash": None, "hash_signature": None,
                                          "temporary": True})
            except OSError as exc:
                raise LibraryError(f"无法展开文件夹资源：{exc}") from exc
        errors, groups = [], []
        if mode == "exact":
            sizes: dict[int, list[dict]] = {}
            for resource in resources:
                sizes.setdefault(resource["size"], []).append(resource)
            hashes: dict[str, list[dict]] = {}
            for candidates in sizes.values():
                if len(candidates) < 2:
                    continue
                for resource in candidates:
                    try:
                        st = Path(resource["path"]).stat()
                        signature = f"{st.st_size}:{st.st_mtime_ns}"
                        digest = (
                            resource["hash"] if signature == resource["hash_signature"] else None
                        )
                        if not digest:
                            h = hashlib.sha256()
                            with open(resource["path"], "rb") as handle:
                                for block in iter(lambda: handle.read(1024 * 1024), b""):
                                    h.update(block)
                            digest = h.hexdigest()
                            if not resource.get("temporary"):
                                with self._lock:
                                    self.db.execute(
                                        "UPDATE resources SET hash=?,hash_signature=? WHERE id=?",
                                        (digest, signature, resource["id"]),
                                    )
                                    self.db.commit()
                        hashes.setdefault(digest, []).append(resource)
                    except OSError as exc:
                        errors.append(f"{resource['name']}: {exc}")
            groups = [
                {"hash": digest, "resources": candidates, "similarity": 100}
                for digest, candidates in hashes.items()
                if len(candidates) > 1
            ]
        else:
            try:
                from PIL import Image, ImageOps
            except ImportError as exc:
                raise LibraryError("相似图片检测需要安装 Pillow。") from exc
            hashes = []
            for resource in resources:
                try:
                    if resource["type"] == "image":
                        with Image.open(resource["path"]) as im:
                            im = ImageOps.exif_transpose(im).convert("L").resize((9, 8))
                            pixels = _pixel_values(im)
                        digest = sum(
                            (pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
                            for y in range(8)
                            for x in range(8)
                        )
                        hashes.append((resource, [(digest, None)]))
                    elif resource["type"] == "video":
                        frame_hashes = self._video_hashes(resource["path"])
                        if frame_hashes:
                            hashes.append((resource, frame_hashes))
                        else:
                            errors.append(f"{resource['name']}: 无法解码代表帧，已跳过。")
                except Exception as exc:
                    errors.append(f"{resource['name']}: {exc}")
            def distance(a, b):
                color_distance = max(abs(x - y) for x, y in zip(a[1], b[1])) / 8 if a[1] and b[1] else 0
                return (a[0] ^ b[0]).bit_count() + color_distance

            # Compare against a group's representative to avoid transitive
            # false positives (A~B and B~C must not force A~C).
            limit = min(max(int(threshold), 0), 20)
            grouped = []
            for resource, digest in hashes:
                placed = False
                for group in grouped:
                    if resource["type"] != group["resources"][0]["type"]:
                        continue
                    representative = group["hashes"][0]
                    distances = [min(distance(a, b) for b in representative) for a in digest]
                    reverse = [min(distance(a, b) for a in digest) for b in representative]
                    score = (sum(distances) / len(distances) + sum(reverse) / len(reverse)) / 2
                    if score <= limit:
                        group["resources"].append(resource)
                        group["hashes"].append(digest)
                        placed = True
                        break
                if not placed:
                    grouped.append({"resources": [resource], "hashes": [digest]})
            groups = [{"resources": group["resources"], "similarity": None}
                      for group in grouped if len(group["resources"]) > 1]
        if compare_all and source_set:
            groups = [
                group for group in groups
                if any(resource.get("id") in source_set for resource in group["resources"])
            ]
        return {"mode": mode, "groups": groups, "errors": errors, "scanned": len(resources), "temporary_scope": temporary_scope, "temporary": bool(temporary_scope)}

    def export_data(
        self,
        categories: list[str] | None = None,
        tags: list[str] | None = None,
        include_resources: bool = True,
    ) -> dict:
        with self._lock:
            selected_categories = [
                c["path"]
                for c in self.categories()
                if categories is None
                or any(c["path"] == x or c["path"].startswith(x + "/") for x in categories)
            ]
            # Ancestors are included so a selected branch retains its hierarchy.
            with_ancestors = set(selected_categories)
            for category in selected_categories:
                parts = category.split("/")
                with_ancestors.update("/".join(parts[:i]) for i in range(1, len(parts)))
            result = {
                "format": "resource-controller",
                "version": 1,
                "exported_at": time.time(),
                "categories": sorted(with_ancestors),
                "tags": [t["name"] for t in self.tags() if tags is None or t["name"] in tags],
            }
            if include_resources:
                result["resources"] = [
                    r
                    for r in self.resources()
                    if (categories is None or r["category"] in selected_categories)
                    and (tags is None or set(tags).intersection(r["tags"]))
                ]
            return result

    def import_data(self, payload: dict, mode: str = "merge", preview: bool = False) -> dict:
        """Import taxonomy and (when present) resource metadata.

        ``merge`` keeps existing resources and adds missing taxonomy rows.  In
        ``replace`` mode the imported taxonomy becomes authoritative for the
        active library: resources represented by the export are matched by
        stable id (then path) and their grade, tags, name and category are
        applied; resources not represented by the export are moved to the
        program trash so the operation remains reversible.  An export made
        with ``include_resources=False`` only replaces taxonomy and moves
        resources from removed categories back to the inbox.  No source bytes
        are deleted and every filesystem/metadata change is journalled.
        """
        with self._lock:
            if payload.get("format") != "resource-controller" or payload.get("version") != 1:
                raise LibraryError("不支持的导入文件格式或版本。")
            if mode not in {"merge", "replace"}:
                raise LibraryError("导入模式只能为合并或替换。")
            cats = set()
            for category in payload.get("categories", []):
                category = self._category(category)
                parts = category.split("/")
                cats.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
            tags = list(
                dict.fromkeys(clean_component(t, tag=True) for t in payload.get("tags", []))
            )
            known = {r[0] for r in self.db.execute("SELECT path FROM categories")}
            steps = []
            resource_updates: dict[str, dict] = {}
            matched_ids: set[str] = set()
            unmatched_imported: list[str] = []
            imported_resources = payload.get("resources") if "resources" in payload else None
            if imported_resources is not None and not isinstance(imported_resources, list):
                raise LibraryError("导入文件中的 resources 必须是数组。")

            # New taxonomy directories are created before resource moves so a
            # matched resource can be moved directly to its imported leaf.
            for category in sorted(cats - known, key=lambda c: (c.count("/"), c)):
                path = self._category_path(category)
                if path.exists():
                    raise LibraryError(f"导入分类与现有文件夹冲突：{category}")
                steps.append({"action": "mkdir", "path": str(path)})

            if mode == "replace":
                existing = [
                    dict(row)
                    for row in self.db.execute("SELECT * FROM resources WHERE trashed=0")
                ]
                by_id = {row["id"]: row for row in existing}
                by_path = {_key(row["path"]): row for row in existing}
                source_keys = {_key(row["path"]) for row in existing}
                destination_keys: dict[str, str] = {}
                matched_source_keys: set[str] = set()

                def imported_category(value):
                    if not value:
                        return None
                    category = self._category(value)
                    if category not in cats:
                        raise LibraryError(f"资源引用了未导入的分类：{category}")
                    return category

                def match_resource(raw):
                    if not isinstance(raw, dict):
                        raise LibraryError("导入文件中的资源记录必须是对象。")
                    candidate = by_id.get(str(raw.get("id"))) if raw.get("id") else None
                    if candidate is None and raw.get("path"):
                        candidate = by_path.get(_key(raw["path"]))
                    return candidate

                # Apply metadata for records that belong to this library.  We
                # deliberately never create a DB row for an external path: an
                # import is metadata-only and must not invent missing files.
                if imported_resources is not None:
                    for raw in imported_resources:
                        candidate = match_resource(raw)
                        if candidate is None:
                            unmatched_imported.append(str(raw.get("id") or raw.get("path") or ""))
                            continue
                        resource_id = candidate["id"]
                        if resource_id in matched_ids:
                            raise LibraryError(f"导入文件重复引用资源：{resource_id}")
                        matched_ids.add(resource_id)
                        matched_source_keys.add(_key(candidate["path"]))
                        resource_type = str(raw.get("type") or candidate["type"])
                        if resource_type != candidate["type"]:
                            raise LibraryError(f"资源类型不一致，无法替换：{candidate['name']}")
                        raw_tags = raw.get("tags", candidate["tags"])
                        if not isinstance(raw_tags, list):
                            raise LibraryError(f"资源标签必须是数组：{candidate['name']}")
                        clean_tags = list(
                            dict.fromkeys(clean_component(tag, tag=True) for tag in raw_tags)
                        )
                        grade = str(raw.get("grade", candidate["grade"]) or "")
                        name = clean_component(raw.get("name", candidate["name"]))
                        category = imported_category(raw.get("category"))
                        filename = build_name(name, grade, clean_tags, candidate["extension"])
                        parent = self._category_path(category) if category else self.source_root
                        if parent is None:
                            raise LibraryError("尚未设置原始目录。")
                        destination = parent / filename
                        if candidate["type"] == "folder" and _inside(parent, Path(candidate["path"])):
                            raise LibraryError("不能将文件夹资源移动到自身内部。")
                        destination_key = _key(destination)
                        previous = destination_keys.get(destination_key)
                        if previous and previous != resource_id:
                            raise LibraryError(f"导入后存在重名资源：{filename}")
                        destination_keys[destination_key] = resource_id
                        # A destination occupied by another matched source
                        # would require a swap. Reject it before any mutation
                        # rather than risking a partial overwrite.
                        occupant = by_path.get(destination_key)
                        if occupant and occupant["id"] != resource_id:
                            raise LibraryError(f"导入后目标已存在，未覆盖：{filename}")
                        updated = dict(candidate)
                        updated.update(
                            name=name,
                            grade=grade,
                            tags=json.dumps(clean_tags, ensure_ascii=False),
                            category=category,
                            path=str(destination),
                            trashed=0,
                        )
                        resource_updates[resource_id] = updated

                # A replacement with no resource payload is still useful for
                # taxonomy-only exports.  Keep resource metadata, but move
                # entries whose old category disappeared back to the inbox.
                for candidate in existing:
                    if candidate["id"] in matched_ids:
                        continue
                    old_category = candidate["category"] or ""
                    if imported_resources is not None:
                        # Explicitly exported resources are authoritative. Any
                        # active record omitted from the export is reversible
                        # moved to the internal trash.
                        parent = self.data_dir / "trash"
                        filename = candidate["id"] + "__" + Path(candidate["path"]).name[:180]
                        destination = parent / filename
                        updated = dict(candidate)
                        updated.update(path=str(destination), category=None, trashed=1)
                    elif old_category and old_category not in cats:
                        parent = self.source_root
                        if parent is None:
                            raise LibraryError("尚未设置原始目录。")
                        destination = parent / Path(candidate["path"]).name
                        updated = dict(candidate)
                        updated.update(path=str(destination), category=None, trashed=0)
                    else:
                        continue
                    destination_key = _key(destination)
                    previous = destination_keys.get(destination_key)
                    if previous and previous != candidate["id"]:
                        raise LibraryError(f"导入后目标已存在，未覆盖：{destination.name}")
                    destination_keys[destination_key] = candidate["id"]
                    if destination_key != _key(candidate["path"]):
                        if destination.exists() and destination_key != _key(candidate["path"]):
                            raise LibraryError(f"导入后目标已存在，未覆盖：{destination.name}")
                        steps.append(
                            {
                                "action": "move",
                                "from": candidate["path"],
                                "to": str(destination),
                                "id": candidate["id"],
                            }
                        )
                    resource_updates[candidate["id"]] = updated

                # Matched resource moves happen after new category directories
                # and omitted-resource moves, but before removed categories are
                # archived. This ordering keeps every source path reachable.
                for candidate in existing:
                    updated = resource_updates.get(candidate["id"])
                    if not updated or updated["path"] == candidate["path"]:
                        continue
                    if any(step.get("id") == candidate["id"] for step in steps):
                        continue
                    destination = Path(updated["path"])
                    if destination.exists() and _key(destination) != _key(candidate["path"]):
                        raise LibraryError(f"导入后目标已存在，未覆盖：{destination.name}")
                    steps.append(
                        {
                            "action": "move",
                            "from": candidate["path"],
                            "to": str(destination),
                            "id": candidate["id"],
                        }
                    )

                # Category directories not present in the replacement are
                # archived only after their indexed resources have left them.
                removed = known - cats
                top_removed = [
                    c
                    for c in removed
                    if not any(c.startswith(other + "/") for other in removed if other != c)
                ]
                for category in top_removed:
                    path = self._category_path(category)
                    if path.exists():
                        steps.append(
                            {
                                "action": "move",
                                "from": str(path),
                                "to": str(
                                    self.data_dir / "trash" / (uuid.uuid4().hex + "__" + path.name)
                                ),
                            }
                        )
            if preview:
                return {
                    "changes": steps,
                    "categories": sorted(cats),
                    "tags": tags,
                    "mode": mode,
                    "resources": list(resource_updates.values()),
                    "matched": len(matched_ids),
                    "unmatched_imported": unmatched_imported,
                }
            self.backup()

            def mutate():
                if mode == "replace":
                    self.db.execute("DELETE FROM categories")
                    self.db.execute("DELETE FROM tags")
                    for resource in resource_updates.values():
                        self.db.execute(
                            """UPDATE resources SET path=?,name=?,grade=?,tags=?,category=?,trashed=?
                               WHERE id=?""",
                            (
                                resource["path"],
                                resource["name"],
                                resource["grade"],
                                resource["tags"],
                                resource["category"],
                                int(resource["trashed"]),
                                resource["id"],
                            ),
                        )
                self.db.executemany(
                    "INSERT OR IGNORE INTO categories VALUES (?)", [(c,) for c in cats]
                )
                if mode == "replace":
                    active_tags = set(tags)
                    for row in self.db.execute("SELECT tags FROM resources WHERE trashed=0"):
                        active_tags.update(_json_load(row[0], []) or [])
                    self.db.executemany(
                        "INSERT OR IGNORE INTO tags VALUES (?)", [(t,) for t in active_tags]
                    )
                else:
                    self.db.executemany("INSERT OR IGNORE INTO tags VALUES (?)", [(t,) for t in tags])

            result = self._transaction("替换分类与标签" if mode == "replace" else "导入分类与标签", steps, mutate)
            result.update({"categories": sorted(cats), "tags": tags, "matched": len(matched_ids), "unmatched_imported": unmatched_imported})
            return result
