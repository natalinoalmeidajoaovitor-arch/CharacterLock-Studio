"""Tests for CharacterLock Model Setup, resumable SHA-256 downloader, and preset workflow seeding."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import re
import tempfile
import threading
import unittest
from pathlib import Path

from app.db import Database
from app.model_setup import (
    STUDIO_MODULES,
    download_file_resumable,
    inspect_models_and_nodes,
    load_manifest,
)
from app.preset_seed import seed_preset_workflows
from app.settings import Settings


REPO_ROOT = Path(__file__).resolve().parents[2]


class RangePayloadHandler(BaseHTTPRequestHandler):
    PAYLOAD = b"CharacterLockStudio-Verified-Model-Test-Payload-" * 1024

    def log_message(self, format, *args):
        return

    def do_GET(self):
        rng = self.headers.get("Range")
        data = self.PAYLOAD
        if rng and rng.startswith("bytes="):
            start_s = rng.split("=", 1)[1].split("-", 1)[0]
            start = int(start_s)
            body = data[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ReleaseSetupTests(unittest.TestCase):
    def test_models_manifest_integrity_and_modular_filtering(self):
        manifest = load_manifest(REPO_ROOT)
        self.assertGreaterEqual(len(manifest["models"]), 18)
        for item in manifest["models"]:
            self.assertTrue(item["url"].startswith("https://huggingface.co/"))
            self.assertGreater(item["size_bytes"], 0)
            self.assertRegex(item["sha256"], re.compile(r"^[0-9a-f]{64}$"))
            self.assertTrue(set(item["modules"]).issubset(STUDIO_MODULES))

        with tempfile.TemporaryDirectory() as tmp:
            voice_only = inspect_models_and_nodes(manifest, Path(tmp), ["voice"])
            self.assertEqual(voice_only["selected_modules"], ["voice"])
            self.assertTrue(all("voice" in m["modules"] for m in voice_only["models"]))
            self.assertEqual(voice_only["summary"]["installed_models"], 0)
            self.assertGreater(voice_only["summary"]["missing_models"], 0)

    def test_preset_workflow_seeding_includes_5s_motion_swap_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            settings = Settings(app_root=REPO_ROOT, data_dir=data_dir, comfy_autostart=False, start_worker=False)
            db = Database(data_dir / "characterlock.sqlite3")
            first = seed_preset_workflows(db, settings)
            self.assertEqual(first["seeded"], 16)
            self.assertFalse(first["skipped"])

            motion = db.one("SELECT * FROM workflows WHERE id=?", ("1396636f21dc4040ac31e931bd656c89",))
            self.assertIsNotNone(motion)
            self.assertEqual(motion["module"], "motion_swap")

            second = seed_preset_workflows(db, settings)
            self.assertEqual(second["seeded"], 0)
            self.assertTrue(second["skipped"])

    def test_resumable_range_download_and_sha256_verification(self):
        server = HTTPServer(("127.0.0.1", 0), RangePayloadHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/test_weight.safetensors"
            payload = RangePayloadHandler.PAYLOAD
            expected_sha = hashlib.sha256(payload).hexdigest()

            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "test_weight.safetensors"
                part = dest.with_name(dest.name + ".part")
                # Pre-populate partial download to exercise HTTP 206 Range resume
                part.write_bytes(payload[:8192])

                res = download_file_resumable(
                    url=url,
                    dest=dest,
                    expected_size=len(payload),
                    expected_sha256=expected_sha,
                    use_aria2c=False,
                    log_fn=lambda _: None,
                )
                self.assertEqual(res["status"], "downloaded_and_verified")
                self.assertTrue(dest.is_file())
                self.assertFalse(part.exists())
                self.assertEqual(dest.read_bytes(), payload)

                # Corrupt hash must raise ValueError and never overwrite target
                bad_dest = Path(tmp) / "corrupt_weight.safetensors"
                with self.assertRaises(ValueError):
                    download_file_resumable(
                        url=url,
                        dest=bad_dest,
                        expected_size=len(payload),
                        expected_sha256="0" * 64,
                        use_aria2c=False,
                        log_fn=lambda _: None,
                    )
                self.assertFalse(bad_dest.exists())
        finally:
            server.shutdown()
            server.server_close()
