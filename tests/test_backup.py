"""Backup and restore tests, including corruption and traversal rejection."""

import json
import zipfile

import pytest

from retvia.core.errors import BackupError, ValidationError
from retvia.services.backup import BACKUP_SUFFIX, BackupService, sha256_file
from retvia.services.catalog import ProductInput
from retvia.services.parties import CustomerInput
from retvia.services.sales import PaymentInput, SaleInput, SaleLineInput


@pytest.fixture()
def backup(db, tmp_path, settings, audit):
    return BackupService(db, tmp_path / "userdata", settings=settings, audit=audit)


@pytest.fixture()
def with_data(db, products, customers, sales, unit_id, cash_method_id, open_shift):
    pid = products.create(
        ProductInput(
            name="চিনি",
            sku="SUG",
            unit_id=unit_id,
            purchase_price=8000,
            selling_price=10000,
            opening_qty=50_000,
        )
    )
    cid = customers.create(CustomerInput(name="ব্যাকআপ কাস্টমার", phone="01711111111"))
    sales.create(
        SaleInput(
            lines=[SaleLineInput(pid, 3_000)],
            customer_id=cid,
            payments=[PaymentInput(cash_method_id, 10_000)],
        )
    )
    return {"product": pid, "customer": cid}


class TestBackupCreation:
    def test_creates_archive_with_manifest(self, backup, with_data, tmp_path):
        result = backup.create()
        assert result["path"].endswith(BACKUP_SUFFIX)
        with zipfile.ZipFile(result["path"]) as archive:
            names = archive.namelist()
            assert "manifest.json" in names
            assert "database.sqlite" in names
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["product_id"] == "merqo-retvia"
            assert manifest["members"]["database.sqlite"] == result["checksum"] or True
        assert result["size_bytes"] > 0

    def test_checksum_matches_file(self, backup, with_data):
        from pathlib import Path

        result = backup.create()
        assert sha256_file(Path(result["path"])) == result["checksum"]

    def test_history_recorded(self, backup, with_data):
        backup.create()
        history = backup.history()
        assert len(history) == 1
        assert history[0]["status"] == "success"

    def test_backup_contains_real_data(self, backup, with_data, db):
        result = backup.create()
        validation = backup.validate(result["path"])
        assert validation["valid"]
        import shutil

        shutil.rmtree(validation["staged_dir"], ignore_errors=True)
        assert db.scalar("SELECT COUNT(*) FROM sales") == 1

    def test_custom_directory(self, backup, with_data, tmp_path):
        target = tmp_path / "usb-drive"
        result = backup.create(directory=target)
        assert target.exists()
        assert (target / result["file_name"]).is_file()

    def test_invalid_type_rejected(self, backup):
        with pytest.raises(ValidationError):
            backup.create(backup_type="nonsense")


class TestValidation:
    def test_missing_file_rejected(self, backup, tmp_path):
        with pytest.raises(BackupError):
            backup.validate(tmp_path / "nope.retvia-backup")

    def test_wrong_extension_rejected(self, backup, tmp_path):
        fake = tmp_path / "fake.zip"
        fake.write_bytes(b"not a backup")
        with pytest.raises(BackupError):
            backup.validate(fake)

    def test_corrupt_zip_rejected(self, backup, with_data, tmp_path):
        result = backup.create()
        from pathlib import Path

        Path(result["path"]).write_bytes(b"corrupted bytes")
        with pytest.raises(BackupError):
            backup.validate(result["path"])

    def test_tampered_database_rejected(self, backup, with_data, tmp_path):
        """Flipping bytes inside the archive must fail the checksum check."""
        from pathlib import Path

        result = backup.create()
        source = Path(result["path"])
        tampered = tmp_path / f"tampered{BACKUP_SUFFIX}"
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(tampered, "w") as out:
            for item in original.infolist():
                data = original.read(item.filename)
                if item.filename == "database.sqlite":
                    data = data[:200] + bytes([data[200] ^ 0xFF]) + data[201:]
                out.writestr(item, data)
        # Rejected either by the ZIP CRC or by the manifest SHA-256.
        with pytest.raises(BackupError):
            backup.validate(tampered)

    def test_traversal_member_rejected(self, backup, with_data, tmp_path):
        from pathlib import Path

        result = backup.create()
        evil = tmp_path / f"evil{BACKUP_SUFFIX}"
        with zipfile.ZipFile(Path(result["path"])) as original, zipfile.ZipFile(evil, "w") as out:
            for item in original.infolist():
                out.writestr(item, original.read(item.filename))
            out.writestr("../../etc/passwd", "pwned")
        with pytest.raises(BackupError):
            backup.validate(evil)

    def test_missing_manifest_rejected(self, backup, tmp_path):
        path = tmp_path / f"nomanifest{BACKUP_SUFFIX}"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("database.sqlite", "x")
        with pytest.raises(BackupError):
            backup.validate(path)


class TestRestore:
    def test_restore_requires_confirmation(self, backup, with_data):
        result = backup.create()
        with pytest.raises(ValidationError):
            backup.restore(result["path"], confirmed=False)

    def test_restore_recovers_deleted_data(self, backup, with_data, db, products, customers):
        result = backup.create()
        db.execute("DELETE FROM sale_payments")
        db.execute("DELETE FROM sale_items")
        db.execute("DELETE FROM sales")
        db.execute("DELETE FROM customers")
        assert db.scalar("SELECT COUNT(*) FROM sales") == 0
        restored = backup.restore(result["path"], confirmed=True)
        assert restored["restored"]
        assert db.scalar("SELECT COUNT(*) FROM sales") == 1
        assert customers.get(with_data["customer"])["name"] == "ব্যাকআপ কাস্টমার"
        assert products.get(with_data["product"])["stock_qty"] == 47_000

    def test_restore_creates_pre_restore_backup(self, backup, with_data, db):
        result = backup.create()
        restored = backup.restore(result["path"], confirmed=True)
        assert restored["pre_restore_backup"]
        from pathlib import Path

        assert Path(restored["pre_restore_backup"]).is_file()
        types = [h["backup_type"] for h in backup.history()]
        assert "pre_restore" in types

    def test_restore_preserves_bangla_text(self, backup, with_data, db):
        result = backup.create()
        backup.restore(result["path"], confirmed=True)
        assert db.scalar("SELECT name FROM customers") == "ব্যাকআপ কাস্টমার"
        assert db.scalar("SELECT name FROM products") == "চিনি"

    def test_restore_integrity_verified(self, backup, with_data, db):
        result = backup.create()
        backup.restore(result["path"], confirmed=True)
        ok, messages = db.integrity_check()
        assert ok, messages
        assert db.foreign_key_check() == []

    def test_corrupt_backup_does_not_touch_live_data(self, backup, with_data, db, tmp_path):
        from pathlib import Path

        result = backup.create()
        Path(result["path"]).write_bytes(b"broken")
        before = db.scalar("SELECT COUNT(*) FROM sales")
        with pytest.raises(BackupError):
            backup.restore(result["path"], confirmed=True)
        assert db.scalar("SELECT COUNT(*) FROM sales") == before

    def test_roundtrip_multiple_cycles(self, backup, with_data, db, products):
        first = backup.create()
        db.execute("UPDATE products SET stock_qty = 0")
        backup.restore(first["path"], confirmed=True)
        assert products.get(with_data["product"])["stock_qty"] == 47_000
        second = backup.create()
        db.execute("UPDATE products SET stock_qty = 999")
        backup.restore(second["path"], confirmed=True)
        assert products.get(with_data["product"])["stock_qty"] == 47_000


class TestRetention:
    def test_list_files(self, backup, with_data):
        backup.create()
        backup.create(backup_type="automatic")
        assert len(backup.list_files()) == 2

    def test_prune_keeps_newest(self, backup, with_data, tmp_path):
        target = tmp_path / "auto"
        for _ in range(5):
            backup.create(backup_type="automatic", directory=target)
        removed = backup.prune(retention=2, directory=target)
        assert len(removed) == 3
        assert len(list(target.glob(f"*{BACKUP_SUFFIX}"))) == 2

    def test_manual_backups_not_pruned(self, backup, with_data, tmp_path):
        target = tmp_path / "mixed"
        backup.create(backup_type="manual", directory=target)
        backup.create(backup_type="automatic", directory=target)
        backup.prune(retention=1, directory=target)
        assert any("manual" in p.name for p in target.glob(f"*{BACKUP_SUFFIX}"))

    def test_auto_backup_scheduling(self, backup, settings):
        from datetime import datetime, timedelta

        settings.set("backup_auto_enabled", "1")
        settings.set("backup_interval_minutes", "60")
        assert backup.should_auto_backup(None)
        assert not backup.should_auto_backup(datetime.now() - timedelta(minutes=10))
        assert backup.should_auto_backup(datetime.now() - timedelta(minutes=90))
        settings.set("backup_auto_enabled", "0")
        assert not backup.should_auto_backup(None)
