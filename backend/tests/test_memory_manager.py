"""Simulated native queue/memory responses; these tests do not execute a GPU."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from app.db import Database, encode, now
from app.memory_manager import AIModelMemoryManager, MemoryManagerError, MIB, model_signature


def graph(model="qwen.safetensors", strength=1):
    return {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": model, "weight_dtype": "default"}}, "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": "detail.safetensors", "strength_model": strength}}, "3": {"class_type": "Sampler", "inputs": {"model": ["2", 0], "prompt": "private scene", "seed": 1}}}


class Native:
    def __init__(self):
        self.busy = False
        self.reserved = 4096 * MIB
        self.releases = 0
        self.release_works = True

    async def queue(self):
        return {"queue_running": [[0, "external"]] if self.busy else [], "queue_pending": []}

    async def system_stats(self):
        return {"system": {"ram_free": 1024}, "devices": [{"type": "cuda", "index": 0, "vram_total": 16384 * MIB, "vram_free": 8000 * MIB, "torch_vram_total": self.reserved, "torch_vram_free": 0}]}

    async def _request(self, method, route, **kwargs):
        assert (method, route) == ("POST", "/free")
        assert kwargs["json"] == {"unload_models": True, "free_memory": True}
        self.releases += 1
        if self.release_works:
            self.reserved = 0


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "db.sqlite3")
        stamp = now()
        self.db.execute("INSERT INTO characters(id,name,consent_confirmed,created_at,updated_at) VALUES(?,?,?,?,?)", ("person", "Test", 1, stamp, stamp))
        self.db.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)", ("workflow", "Test", "character_lab", encode(graph()), "{}", "{}", None, "local.json", "hash", stamp))
        self.native = Native()
        self.manager = AIModelMemoryManager(self.native, self.db, self.root, idle_timeout=.01, release_timeout=.03, poll_seconds=.001, settle_seconds=0, nvidia_reader=None)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, job_id, status="preparing", error=None):
        stamp = now()
        self.db.execute("INSERT INTO jobs(id,module,character_id,workflow_id,status,parameters,asset_inputs,client_id,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (job_id, "character_lab", "person", "workflow", status, "{}", "{}", job_id, encode(error) if error else None, stamp, stamp))

    def test_signature_uses_reachable_weights_not_tab_prompt_seed_or_ids(self):
        a = graph()
        b = graph()
        b["3"]["inputs"].update(prompt="different", seed=123)
        b["99"] = {"class_type": "UNETLoader", "inputs": {"unet_name": "unused.safetensors"}}
        self.assertEqual(model_signature(a, ["3"])["fingerprint"], model_signature(b, ["3"])["fingerprint"])
        self.assertNotEqual(model_signature(a, ["3"])["fingerprint"], model_signature(graph(strength=.5), ["3"])["fingerprint"])
        self.assertNotEqual(model_signature(a, ["3"])["fingerprint"], model_signature(graph("h3.safetensors"), ["3"])["fingerprint"])

    async def test_transition_releases_then_same_weights_reuse(self):
        for name in ["one", "two", "three"]:
            self.job(name, "queued")
        for name, model in [("one", "qwen.safetensors"), ("two", "qwen.safetensors"), ("three", "h3.safetensors")]:
            self.db.execute("UPDATE jobs SET status='preparing' WHERE id=?", (name,))
            async with self.manager.execution(name):
                await self.manager.prepare(name, graph(model), ["3"])
                self.db.execute("UPDATE jobs SET status='succeeded',prompt_id='native' WHERE id=?", (name,))
                await self.manager.finish(name, self.db.one("SELECT * FROM jobs WHERE id=?", (name,)))
        self.assertEqual(self.native.releases, 2)
        events = json.loads((self.root / "jobs/two/memory.json").read_text())["events"]
        self.assertIn("reusing_models", [event["phase"] for event in events])

    async def test_http_ack_without_low_memory_blocks_submission(self):
        self.job("one")
        self.native.release_works = False
        async with self.manager.execution("one"):
            with self.assertRaises(MemoryManagerError) as caught:
                await self.manager.prepare("one", graph(), ["3"])
        self.assertEqual(caught.exception.code, "memory_release_unverified")
        self.assertEqual(self.native.releases, 1)

    async def test_busy_native_queue_never_unloads(self):
        self.job("one")
        self.native.busy = True
        async with self.manager.execution("one"):
            with self.assertRaises(MemoryManagerError) as caught:
                await self.manager.prepare("one", graph(), ["3"])
        self.assertEqual(caught.exception.code, "memory_engine_busy")
        self.assertEqual(self.native.releases, 0)

    async def test_lease_serializes_callers_and_is_required(self):
        self.job("one", "queued")
        with self.assertRaises(MemoryManagerError):
            await self.manager.prepare("one", graph(), ["3"])
        acquired = asyncio.Event()
        async def second():
            async with self.manager.execution("two"):
                acquired.set()
        async with self.manager.execution("one"):
            task = asyncio.create_task(second())
            await asyncio.sleep(.005)
            self.assertFalse(acquired.is_set())
        await task
        self.assertTrue(acquired.is_set())

    async def test_resumed_job_is_only_observed(self):
        self.job("one", "running")
        self.native.busy = True
        async with self.manager.execution("one", resumed=True):
            await self.manager.finish("one", self.db.one("SELECT * FROM jobs WHERE id='one'"))
        self.assertEqual(self.native.releases, 0)

    async def test_oom_cleans_once_without_replaying_and_keeps_error(self):
        self.job("one", "failed", {"message": "CUDA out of memory"})
        async with self.manager.execution("one"):
            await self.manager.finish("one", self.db.one("SELECT * FROM jobs WHERE id='one'"))
        self.assertEqual( self.native.releases, 1)
        row = self.db.one("SELECT * FROM jobs WHERE id='one'")
        self.assertEqual(row["status"], "failed")
        self.assertIn("CUDA out of memory", row["error"])
        self.assertIsNone(row["prompt_id"])

    async def test_cuda_malloc_async_active_bytes_must_drop_before_submission(self):
        self.job("one")
        self.native.reserved = 0
        self.native.release_works = False
        async def async_stats():
            return {"system": {"ram_free": 1024}, "devices": [{"type": "cuda", "index": 0, "vram_total": 16384 * MIB, "vram_free": 8000 * MIB, "torch_vram_total": 0, "torch_vram_free": -4096 * MIB}]}
        self.native.system_stats = async_stats
        async with self.manager.execution("one"):
            with self.assertRaises(MemoryManagerError) as caught:
                await self.manager.prepare("one", graph(), ["3"])
        self.assertEqual(caught.exception.code, "memory_release_unverified")


if __name__ == "__main__":
    unittest.main()
