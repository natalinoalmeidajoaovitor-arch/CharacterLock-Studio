"""HTTP transport doubles verify contracts; they never replace product execution."""
from pathlib import Path
import tempfile
import unittest

import httpx

from app.comfy import ComfyClient, ComfyError


class ComfyClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_routes_and_submit_body(self):
        requests = []
        async def handler(request):
            requests.append(request)
            if request.url.path == "/prompt":
                return httpx.Response(200, json={"prompt_id": "upstream-id", "number": 1, "node_errors": {}})
            if request.url.path == "/view":
                return httpx.Response(200, content=b"actual fixture bytes")
            return httpx.Response(200, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ComfyClient("http://127.0.0.1:8188", http_client=http)
            await client.system_stats()
            await client.object_info()
            await client.queue()
            await client.history("upstream-id")
            result = await client.submit({"4": {"class_type": "FixtureNode", "inputs": {}}}, "client-fixture")
            data = await client.download_output({"filename": "result.mp4", "subfolder": "characterlock", "type": "output"})
        self.assertEqual([r.url.path for r in requests], ["/system_stats", "/object_info", "/queue", "/history/upstream-id", "/prompt", "/view"])
        self.assertEqual(result["prompt_id"], "upstream-id")
        self.assertIn(b'"client_id":"client-fixture"', requests[4].content)
        self.assertEqual(data, b"actual fixture bytes")
        self.assertEqual(requests[-1].url.params["type"], "output")

    async def test_ui_graph_never_posts_and_validation_errors_preserved(self):
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(400, json={"error": {"message": "bad graph"}, "node_errors": {"4": {"errors": ["missing model"]}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ComfyClient("http://localhost:8188", http_client=http)
            with self.assertRaises(ComfyError):
                await client.submit({"nodes": []})
            self.assertEqual(calls, 0)
            with self.assertRaises(ComfyError) as caught:
                await client.submit({"4": {"class_type": "FixtureNode", "inputs": {}}})
            self.assertEqual(caught.exception.status_code, 400)
            self.assertIn("node_errors", caught.exception.details)

    async def test_submission_timeout_is_never_retried(self):
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("fixture timeout", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ComfyClient("http://localhost:8188", http_client=http)
            with self.assertRaises(ComfyError) as caught:
                await client.submit({"4": {"class_type": "FixtureNode", "inputs": {}}})
            self.assertTrue(caught.exception.details["submission_uncertain"])
            self.assertEqual(calls, 1)

    async def test_image_upload_only_and_safe_filename(self):
        requests = []
        async def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"name": "reference.png", "subfolder": "characterlock", "type": "input"})
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "reference.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture bytes")
            audio = Path(directory) / "reference.wav"
            audio.write_bytes(b"RIFFfixture")
            disguised = Path(directory) / "fake.png"
            disguised.write_bytes(b"not an image")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                client = ComfyClient("http://localhost:8188", http_client=http)
                result = await client.upload_file(image)
                self.assertEqual(result["name"], "reference.png")
                for path in (audio, disguised):
                    with self.assertRaises(ComfyError):
                        await client.upload_file(path)
                for descriptor in ({"filename": "../secret"}, {"filename": "ok.png", "subfolder": "..\\secret"}, {"filename": "C:\\secret"}, {"filename": "ok.png", "type": "arbitrary"}):
                    with self.assertRaises(ComfyError):
                        await client.download_output(descriptor)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/upload/image")
        self.assertIn(b'name="image"', requests[0].content)

    async def test_bad_json_and_missing_prompt_id_rejected(self):
        for response in (httpx.Response(200, content=b"not JSON"), httpx.Response(200, json=[]), httpx.Response(200, json={})):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as http:
                with self.assertRaises(ComfyError):
                    await ComfyClient("http://localhost:8188", http_client=http).submit({"4": {"class_type": "FixtureNode", "inputs": {}}})

    async def test_download_limit_checked_before_unbounded_read(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"oversized"))) as http:
            client = ComfyClient("http://localhost:8188", http_client=http, max_output_bytes=4)
            with self.assertRaises(ComfyError):
                await client.download_output({"filename": "result.mp4"})


if __name__ == "__main__":
    unittest.main()
