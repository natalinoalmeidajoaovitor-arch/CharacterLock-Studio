"""Backup checks use temporary data only, never the user's character library."""
import importlib.util
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("studio_backup", Path(__file__).with_name("backup.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.database = self.data / "characterlock.sqlite3"
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("CREATE TABLE characters (name TEXT)")
            conn.execute("INSERT INTO characters VALUES ('backup-test')")
        (self.data / "characters").mkdir()
        (self.data / "characters" / "asset.bin").write_bytes(b"test-only")
        (self.data / "tmp").mkdir()
        (self.data / "tmp" / "incomplete.part").write_bytes(b"not-backed-up")

    def tearDown(self):
        self.temp.cleanup()

    def test_snapshot_contains_database_and_assets_but_not_temporary_files(self):
        archive_path = module.backup(self.data, self.root / "backups")
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            self.assertIn("data/characters/asset.bin", names)
            self.assertNotIn("data/tmp/incomplete.part", names)
            self.assertNotIn("data/.server.lock", names)
            restored = self.root / "restored.sqlite3"
            restored.write_bytes(archive.read("data/characterlock.sqlite3"))
        with closing(sqlite3.connect(restored)) as conn:
            self.assertEqual(conn.execute("SELECT name FROM characters").fetchone()[0], "backup-test")

    def test_running_backend_lock_blocks_backup(self):
        lock = module.InstanceLock(self.data / ".server.lock")
        lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                module.backup(self.data, self.root / "backups")
        finally:
            lock.release()

    def test_refuses_destination_inside_data(self):
        with self.assertRaises(ValueError):
            module.backup(self.data, self.data / "backups")


if __name__ == "__main__":
    unittest.main()
