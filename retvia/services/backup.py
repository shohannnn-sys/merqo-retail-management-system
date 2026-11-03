"""Backup and restore with validation, checksums and pre-restore safety.

A backup is a ZIP archive (``.retvia-backup``) containing:
  * ``database.sqlite`` — a consistent ``VACUUM INTO`` snapshot (WAL-safe)
  * ``manifest.json``   — version, timestamp and SHA-256 of every member
  * ``assets/…``        — business logo and other required business assets

Restore never overwrites live data until the archive has been fully validated
and a pre-restore backup of the current data has been taken.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .. import __product_id__, __version__
from ..core.errors import BackupError, ValidationError
from ..data.db import Database
from .audit import AuditService
from .settings import BusinessProfileService, SettingsService

BACKUP_SUFFIX = ".retvia-backup"
MANIFEST_NAME = "manifest.json"
DB_MEMBER = "database.sqlite"
BACKUP_FORMAT = 1
_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(name: str) -> bool:
    """Reject absolute paths and traversal in archive members."""
    pure = PurePosixPath(name)
    return not (pure.is_absolute() or ".." in pure.parts or name.startswith("/") or "\\" in name)


class BackupService:
    def __init__(
        self, db: Database, data_dir: Path, *, settings: SettingsService | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self.db = db
        self.data_dir = Path(data_dir)
        self.settings = settings or SettingsService(db)
        self.audit = audit or AuditService(db)
        self.profile = BusinessProfileService(db)

    # ---------------------------------------------------------------- paths
    def backup_dir(self) -> Path:
        configured = self.settings.get("backup_dir", "")
        path = Path(configured) if configured else self.data_dir / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # --------------------------------------------------------------- create
    def create(
        self, *, backup_type: str = "manual", directory: Path | None = None, notes: str = ""
    ) -> dict[str, Any]:
        if backup_type not in ("manual", "automatic", "pre_restore", "pre_update"):
            raise ValidationError("ব্যাকআপের ধরন সঠিক নয়")
        target_dir = Path(directory) if directory else self.backup_dir()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackupError("ব্যাকআপ ফোল্ডার তৈরি করা যায়নি", detail=str(exc)) from exc
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        final_path = target_dir / f"retvia-{backup_type}-{stamp}{BACKUP_SUFFIX}"

        stage = Path(tempfile.mkdtemp(prefix="retvia-backup-"))
        try:
            snapshot = stage / DB_MEMBER
            self.db.vacuum_into(snapshot)
            ok, messages = _check_sqlite_file(snapshot)
            if not ok:
                raise BackupError("ডেটাবেস স্ন্যাপশটের ইন্টিগ্রিটি যাচাই ব্যর্থ", detail="; ".join(messages))

            members: dict[str, str] = {DB_MEMBER: sha256_file(snapshot)}
            asset_files: list[tuple[Path, str]] = []
            logo = self.profile.get().logo_path
            if logo:
                logo_path = Path(logo)
                if logo_path.is_file() and _is_within(logo_path, self.data_dir):
                    member = f"assets/{logo_path.name}"
                    asset_files.append((logo_path, member))
                    members[member] = sha256_file(logo_path)

            profile = self.profile.get()
            manifest = {
                "format": BACKUP_FORMAT,
                "product_id": __product_id__,
                "app_version": __version__,
                "schema_version": self.db.schema_version,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "backup_type": backup_type,
                "business_name": profile.name,
                "members": members,
                "notes": notes,
            }
            manifest_path = stage / MANIFEST_NAME
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            temp_archive = stage / "archive.zip"
            with zipfile.ZipFile(temp_archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(manifest_path, MANIFEST_NAME)
                archive.write(snapshot, DB_MEMBER)
                for source, member in asset_files:
                    archive.write(source, member)
            shutil.move(str(temp_archive), str(final_path))
            checksum = sha256_file(final_path)
            size = final_path.stat().st_size
            self.db.execute(
                """INSERT INTO backup_history
                   (file_path, file_name, size_bytes, checksum, backup_type, status, notes)
                   VALUES (?,?,?,?,?, 'success', ?)""",
                (str(final_path), final_path.name, size, checksum, backup_type, notes),
            )
            self.audit.log(
                "backup", None, "create", f"ব্যাকআপ তৈরি: {final_path.name} ({size} বাইট)",
                after={"type": backup_type, "checksum": checksum[:16]},
            )
            return {
                "path": str(final_path), "file_name": final_path.name,
                "size_bytes": size, "checksum": checksum, "backup_type": backup_type,
            }
        except BackupError:
            raise
        except (OSError, zipfile.BadZipFile, sqlite3.Error) as exc:
            raise BackupError("ব্যাকআপ তৈরি করা যায়নি", detail=str(exc)) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    # ------------------------------------------------------------- validate
    def validate(self, archive_path: Path | str) -> dict[str, Any]:
        path = Path(archive_path)
        if not path.is_file():
            raise BackupError("ব্যাকআপ ফাইল খুঁজে পাওয়া যায়নি")
        if path.suffix != BACKUP_SUFFIX:
            raise BackupError("এটি বৈধ Retvia ব্যাকআপ ফাইল নয়")
        stage = Path(tempfile.mkdtemp(prefix="retvia-validate-"))
        try:
            try:
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    if MANIFEST_NAME not in names or DB_MEMBER not in names:
                        raise BackupError("ব্যাকআপ ফাইলে প্রয়োজনীয় অংশ নেই")
                    if any(not _safe_member(n) for n in names):
                        raise BackupError("ব্যাকআপ ফাইলে অনিরাপদ পাথ রয়েছে — রিস্টোর করা যাবে না")
                    manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
                    if manifest.get("format") != BACKUP_FORMAT:
                        raise BackupError("ব্যাকআপ ফরম্যাট সংস্করণ সমর্থিত নয়")
                    if manifest.get("product_id") != __product_id__:
                        raise BackupError("এই ব্যাকআপ অন্য প্রোডাক্টের")
                    declared = manifest.get("members", {})
                    for member, expected in declared.items():
                        if member not in names:
                            raise BackupError(f"ব্যাকআপে '{member}' অনুপস্থিত")
                        target = stage / member
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as src, target.open("wb") as dst:
                            shutil.copyfileobj(src, dst, _CHUNK)
                        if sha256_file(target) != expected:
                            raise BackupError(f"ব্যাকআপের '{member}' চেকসাম মিলছে না — ফাইল নষ্ট")
            except zipfile.BadZipFile as exc:
                raise BackupError("ব্যাকআপ ফাইল নষ্ট (ZIP পড়া যায়নি)") from exc
            ok, messages = _check_sqlite_file(stage / DB_MEMBER)
            if not ok:
                raise BackupError("ব্যাকআপের ডেটাবেস নষ্ট", detail="; ".join(messages))
            schema_version = int(manifest.get("schema_version", 0))
            if schema_version > self.db.schema_version:
                raise BackupError(
                    "ব্যাকআপটি নতুন সংস্করণের — আগে সফটওয়্যার আপডেট করুন"
                )
            return {
                "valid": True, "manifest": manifest, "staged_dir": str(stage),
                "schema_version": schema_version, "checksum": sha256_file(path),
            }
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    # -------------------------------------------------------------- restore
    def restore(self, archive_path: Path | str, *, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise ValidationError("রিস্টোর নিশ্চিত করা হয়নি")
        validation = self.validate(archive_path)
        stage = Path(validation["staged_dir"])
        pre_restore: dict[str, Any] | None = None
        try:
            # 1. Protect current data before anything is replaced.
            pre_restore = self.create(backup_type="pre_restore", notes=f"রিস্টোরের আগে: {Path(archive_path).name}")
            staged_db = stage / DB_MEMBER

            # 2. Migrate the staged copy forward if the backup is older.
            staged = Database(staged_db)
            try:
                staged.migrate()
                ok, messages = staged.integrity_check()
                if not ok:
                    raise BackupError("রিস্টোরের পর ইন্টিগ্রিটি যাচাই ব্যর্থ", detail="; ".join(messages))
            finally:
                staged.close()

            # 3. Swap the live database file.
            live = self.db.path
            self.db.close()
            for suffix in ("-wal", "-shm"):
                side = Path(str(live) + suffix)
                if side.exists():
                    side.unlink()
            shutil.copyfile(staged_db, live)

            # 4. Restore business assets.
            for member in validation["manifest"].get("members", {}):
                if member.startswith("assets/"):
                    source = stage / member
                    if source.is_file():
                        target = self.data_dir / "assets" / "business" / source.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)

            # 5. Reopen and verify.
            self.db.reopen()
            ok, messages = self.db.integrity_check()
            if not ok:
                raise BackupError("রিস্টোরের পর ডেটাবেস ইন্টিগ্রিটি ব্যর্থ", detail="; ".join(messages))
            violations = self.db.foreign_key_check()
            if violations:
                raise BackupError("রিস্টোরের পর ফরেন-কী সমস্যা পাওয়া গেছে", detail=str(violations[:5]))
            # The pre-restore record was written to the database we just
            # replaced, so re-record it (and the restore itself) in the new one.
            if pre_restore:
                self.db.execute(
                    """INSERT INTO backup_history
                       (file_path, file_name, size_bytes, checksum, backup_type, status, notes)
                       VALUES (?,?,?,?, 'pre_restore', 'success', ?)""",
                    (
                        pre_restore["path"], pre_restore["file_name"],
                        pre_restore["size_bytes"], pre_restore["checksum"],
                        "রিস্টোরের আগে স্বয়ংক্রিয় সুরক্ষা ব্যাকআপ",
                    ),
                )
            self.db.execute(
                """INSERT INTO backup_history
                   (file_path, file_name, size_bytes, checksum, backup_type, status, notes)
                   VALUES (?,?,?,?, 'manual', 'success', ?)""",
                (
                    str(archive_path), Path(archive_path).name,
                    Path(archive_path).stat().st_size if Path(archive_path).is_file() else 0,
                    validation["checksum"], "এই ব্যাকআপ থেকে রিস্টোর সম্পন্ন হয়েছে",
                ),
            )
            self.audit.log(
                "backup", None, "restore",
                f"রিস্টোর সম্পন্ন: {Path(archive_path).name}",
                after={"pre_restore_backup": pre_restore["file_name"] if pre_restore else ""},
            )
            return {
                "restored": True,
                "pre_restore_backup": pre_restore["path"] if pre_restore else "",
                "business_name": validation["manifest"].get("business_name", ""),
                "counts": self.db.table_counts(),
            }
        except BackupError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise BackupError(
                "রিস্টোর ব্যর্থ — আগের ডেটা ব্যাকআপ থেকে ফেরত আনা যাচ্ছে",
                detail=str(exc),
            ) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    # ------------------------------------------------------------ retention
    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.query(
                "SELECT * FROM backup_history ORDER BY id DESC LIMIT ?", (limit,)
            )
        ]

    def list_files(self, directory: Path | None = None) -> list[dict[str, Any]]:
        folder = Path(directory) if directory else self.backup_dir()
        if not folder.is_dir():
            return []
        files = []
        for path in sorted(folder.glob(f"*{BACKUP_SUFFIX}"), reverse=True):
            stat = path.stat()
            files.append(
                {"path": str(path), "file_name": path.name, "size_bytes": stat.st_size,
                 "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")}
            )
        return files

    def prune(self, *, retention: int | None = None, directory: Path | None = None) -> list[str]:
        keep = retention if retention is not None else self.settings.get_int("backup_retention", 20)
        if keep <= 0:
            return []
        folder = Path(directory) if directory else self.backup_dir()
        candidates = sorted(
            folder.glob(f"retvia-automatic-*{BACKUP_SUFFIX}"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        removed = []
        for path in candidates[keep:]:
            try:
                path.unlink()
                removed.append(str(path))
            except OSError:
                continue
        return removed

    def should_auto_backup(self, last_run: datetime | None) -> bool:
        if not self.settings.get_bool("backup_auto_enabled", True):
            return False
        if last_run is None:
            return True
        interval = max(5, self.settings.get_int("backup_interval_minutes", 120))
        return datetime.now() - last_run >= timedelta(minutes=interval)


def _check_sqlite_file(path: Path) -> tuple[bool, list[str]]:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
            messages = [str(r[0]) for r in rows]
            return messages == ["ok"], messages
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, [str(exc)]


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
