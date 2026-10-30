"""Lifecycle tests use injected process/HTTP doubles; they never launch ComfyUI."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.engine_manager import EngineManager
from app.settings import Settings


class ProcessFixture:
    def __init__(self, pid=424242):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        raise AssertionError("The lifecycle must never terminate a running engine")


class HttpFixture:
    def __init__(self, ready=False, malformed=False):
        self.ready, self.malformed = ready, malformed

    async def system_stats(self):
        if not self.ready:
            raise ConnectionError("Fixture service is not listening")
        if self.malformed:
            return {"unrelated_service": True}
        return {"system": {"comfyui_version": "fixture", "python_version": "fixture", "embedded_python": True}, "devices": []}

    async def object_info(self):
        if not self.ready:
            raise ConnectionError("Fixture service is not ready")
        return {"FixtureNode": {"input": {}}}


async def port_closed():
    return False


async def port_occupied():
    return True


class EngineManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.portable = self.directory / "PortableFixture"
        (self.portable / "python_embeded").mkdir(parents=True)
        (self.portable / "ComfyUI").mkdir()
        (self.portable / "python_embeded" / "python.exe").write_bytes(b"not executable: test fixture")
        (self.portable / "ComfyUI" / "main.py").write_text("# test fixture, never executed", encoding="utf-8")
        self.settings = Settings(data_dir=self.directory, comfyui_dir=self.portable, engine_startup_timeout=0.025,
                                 engine_probe_seconds=0.001, engine_monitor_seconds=0.001, engine_recovery_backoff=0)
        self.http = HttpFixture()
        self.calls = []
        self.processes = []
        self.managers = []

    async def asyncTearDown(self):
        for manager in self.managers:
            await manager.close()
        self.temp.cleanup()

    def factory(self, command, **kwargs):
        self.calls.append((command, kwargs))
        process = ProcessFixture(424242 + len(self.calls))
        self.processes.append(process)
        return process

    def manager(self, **overrides):
        options = {"process_factory": self.factory, "process_check": lambda pid, exe: False, "port_probe": port_closed}
        options.update(overrides)
        manager = EngineManager(self.settings, self.http, **options)
        self.managers.append(manager)
        return manager

    async def test_reuses_healthy_real_http_shape_without_process(self):
        self.http.ready = True
        manager = self.manager()
        self.assertTrue(await manager.ensure_running())
        self.assertEqual(self.calls, [])
        self.assertEqual(manager.snapshot()["state"], "ready")
        self.assertFalse(manager.snapshot()["owned_process"])

    async def test_hidden_spawn_exact_verified_command_and_no_shutdown_kill(self):
        def factory(command, **kwargs):
            process = self.factory(command, **kwargs)
            self.http.ready = True
            return process
        manager = self.manager(process_factory=factory)
        self.assertTrue(await manager.ensure_running())
        command, kwargs = self.calls[0]
        self.assertEqual(command, [str(self.portable / "python_embeded" / "python.exe"), "-s", str(self.portable / "ComfyUI" / "main.py"), "--windows-standalone-build", "--disable-auto-launch", "--listen", "127.0.0.1", "--port", "8188"])
        self.assertEqual(kwargs["cwd"], str(self.portable))
        self.assertFalse(kwargs["shell"])
        if os.name == "nt":
            self.assertTrue(kwargs["creationflags"] & 0x08000000)
        self.assertEqual(manager.snapshot()["log_file"], "comfyui.log")
        self.assertEqual(json.loads(manager.record_path.read_text())["pid"], self.processes[0].pid)
        await manager.close()  # No terminate call; process remains available for reopening Studio.
        self.assertIsNone(self.processes[0].returncode)

    async def test_hidden_spawn_uses_utf8_child_environment_without_global_changes(self):
        manager = self.manager()
        with patch.dict(os.environ, {"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252", "CHARACTERLOCK_TEST_INHERITED": "preserved"}):
            manager._spawn()
            environment = self.calls[0][1]["env"]
            self.assertEqual(environment["PYTHONUTF8"], "1")
            self.assertEqual(environment["PYTHONIOENCODING"], "utf-8")
            self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
            self.assertEqual(environment["TRANSFORMERS_OFFLINE"], "1")
            self.assertEqual(environment["CHARACTERLOCK_TEST_INHERITED"], "preserved")
            self.assertEqual(os.environ["PYTHONUTF8"], "0")
            self.assertEqual(os.environ["PYTHONIOENCODING"], "cp1252")

    async def test_confirm_ready_resumes_failed_monitor_without_spawning_or_owning_external_service(self):
        manager = self.manager(port_probe=port_occupied)
        manager.request_start()
        await manager.task
        self.assertEqual(manager.state, "failed")
        self.http.ready = True
        self.assertTrue(await manager._ready())
        previous_task = manager.task
        result = manager.confirm_ready()
        self.assertEqual(result["state"], "ready")
        self.assertFalse(result["owned_process"])
        self.assertIsNone(result["pid"])
        self.assertIsNot(manager.task, previous_task)
        self.assertFalse(manager.task.done())
        resumed_task = manager.task
        manager.confirm_ready()
        self.assertIs(manager.task, resumed_task)
        await asyncio.sleep(0.004)
        self.assertEqual(self.calls, [])

    async def test_confirm_ready_preserves_spent_automatic_recovery_budget(self):
        manager = self.manager(port_probe=port_occupied)
        manager.automatic_recoveries = 1
        manager.set_state("failed", "Fixture exhausted recovery")
        self.http.ready = True
        manager.confirm_ready()
        self.assertEqual(manager.automatic_recoveries, 1)
        self.http.ready = False
        await asyncio.wait_for(manager.task, timeout=0.2)
        self.assertEqual(manager.state, "failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(manager.automatic_recoveries, 1)

    async def test_concurrent_ensure_and_start_requests_do_not_duplicate(self):
        def factory(command, **kwargs):
            process = self.factory(command, **kwargs)
            self.http.ready = True
            return process
        manager = self.manager(process_factory=factory)
        result = await asyncio.gather(manager.ensure_running(), manager.ensure_running())
        self.assertEqual(result, [True, True])
        self.assertEqual(len(self.calls), 1)
        manager.request_start()
        first_task = manager.task
        manager.request_start()
        self.assertIs(manager.task, first_task)
        await manager.close()
        self.assertEqual(len(self.calls), 1)

    async def test_timeout_retains_live_process_and_retry_never_duplicates(self):
        manager = self.manager()
        self.assertFalse(await manager.ensure_running())
        self.assertEqual(manager.snapshot()["state"], "failed")
        self.assertTrue(manager.snapshot()["can_retry"])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(await manager.ensure_running())
        self.assertEqual(len(self.calls), 1)

    async def test_restart_recognizes_verified_record_without_spawn(self):
        manager = self.manager(process_check=lambda pid, exe: pid == 41)
        manager.record_path.write_text(json.dumps({"pid": 41, "executable": str(self.portable / "python_embeded" / "python.exe")}), encoding="utf-8")
        self.assertFalse(await manager.ensure_running())
        self.assertEqual(self.calls, [])
        self.assertEqual(manager.snapshot()["pid"], 41)

    async def test_occupied_port_and_unrelated_http_are_never_assumed_ready_or_replaced(self):
        self.http.ready, self.http.malformed = True, True
        manager = self.manager(port_probe=port_occupied)
        self.assertFalse(await manager.ensure_running())
        self.assertEqual(self.calls, [])
        self.assertEqual(manager.snapshot()["state"], "failed")

    async def test_missing_installation_fails_without_installing_or_spawning(self):
        self.settings.comfyui_dir = self.directory / "MissingPortable"
        manager = self.manager()
        self.assertFalse(await manager.ensure_running())
        self.assertIn("CHARACTERLOCK_COMFYUI_DIR", manager.snapshot()["message"])
        self.assertEqual(self.calls, [])
        self.assertFalse(self.settings.comfyui_dir.exists())

    async def test_monitor_recovers_once_then_stops_crash_loop(self):
        def factory(command, **kwargs):
            process = self.factory(command, **kwargs)
            self.http.ready = True
            return process
        manager = self.manager(process_factory=factory)
        manager.start()
        for _ in range(200):
            if len(self.calls) == 1 and manager.state == "ready":
                break
            await asyncio.sleep(0.001)
        self.http.ready = False
        self.processes[0].returncode = 1
        for _ in range(200):
            if len(self.calls) == 2 and manager.state == "ready":
                break
            await asyncio.sleep(0.001)
        self.assertEqual(len(self.calls), 2)
        self.http.ready = False
        self.processes[1].returncode = 1
        for _ in range(200):
            if manager.state == "failed":
                break
            await asyncio.sleep(0.001)
        self.assertEqual(manager.state, "failed")
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
