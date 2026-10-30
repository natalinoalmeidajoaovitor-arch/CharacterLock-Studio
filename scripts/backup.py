"""Consistent local backup. Stop the Studio first; never touches ComfyUI."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "backend"))
from app.db import InstanceLock  # noqa: E402


def backup(data_dir: Path, destination: Path) -> Path:
    data_dir = data_dir.resolve(strict=True)
    destination = destination.resolve()
    if destination == data_dir or data_dir in destination.parents:
        raise ValueError("O destino de backup deve ficar fora da pasta data.")
    database = data_dir / "characterlock.sqlite3"
    if not database.is_file():
        raise ValueError("Banco characterlock.sqlite3 não encontrado; inicie o Studio primeiro.")
    # Same OS lock as the backend; a live server cannot mutate files while copying.
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = destination / f"characterlock-{stamp}.zip"
    lock = InstanceLock(data_dir / ".server.lock")
    lock.acquire()
    try:
        with tempfile.TemporaryDirectory(prefix="characterlock-backup-") as tmp:
            snapshot = Path(tmp) / database.name
            with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(snapshot)) as out:
                source.backup(out)
            with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, "data/characterlock.sqlite3")
                for item in data_dir.rglob("*"):
                    relative = item.relative_to(data_dir)
                    if item.is_symlink():
                        raise ValueError(f"Backup recusado: link simbólico em {relative}.")
                    if not item.is_file() or relative.parts[0] in {"tmp", "logs"}:
                        continue
                    if item.name in {"characterlock.sqlite3", "characterlock.sqlite3-wal", "characterlock.sqlite3-shm", ".server.lock"}:
                        continue
                    if data_dir not in item.resolve().parents:
                        raise ValueError("Arquivo fora da biblioteca durante backup.")
                    archive.write(item, "data/" + relative.as_posix())
                archive.writestr("backup.json", json.dumps({"format": 1, "created_at": stamp, "restore": "Stop Studio; restore data into a new directory; set CHARACTERLOCK_DATA_DIR."}))
        return target
    except BaseException:
        if target.exists():
            target.unlink()
        raise
    finally:
        lock.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT / "data")
    parser.add_argument("--destination", type=Path, default=PROJECT / "backups")
    args = parser.parse_args()
    print(backup(args.data_dir, args.destination))
