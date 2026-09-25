from __future__ import annotations

import base64
import contextlib
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

from PIL import Image
from PIL.Image import DecompressionBombError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import aiflow_image as runtime  # noqa: E402


LAUNCHER_KEYS = (
    "AIFLOW_TOOL",
    "AIFLOW_BASE_URL",
    "AIFLOW_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_KEY",
)


def png_bytes(width: int = 16, height: int = 16) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (22, 82, 140)).save(buffer, format="PNG")
    return buffer.getvalue()


def models_payload(*model_ids: str) -> dict[str, object]:
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "owned_by": "provider-internal-marker",
                "supports_image_generation": True,
                "route": "secret-route-marker",
            }
            for model_id in model_ids
        ],
    }


def image_payload(*, width: int = 16, height: int = 16, declared_size: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "created": 1,
        "data": [{"b64_json": base64.b64encode(png_bytes(width, height)).decode("ascii")}],
        "output_format": "png",
        "quality": "medium",
        "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
    }
    if declared_size is not None:
        result["size"] = declared_size
    return result


@contextlib.contextmanager
def launcher_environment(tool: str, base_url: str, api_key: str):
    original = dict(os.environ)
    try:
        for key in LAUNCHER_KEYS:
            os.environ.pop(key, None)
        os.environ["AIFLOW_TOOL"] = tool
        if tool == "codex":
            os.environ["OPENAI_BASE_URL"] = base_url.rstrip("/") + "/llm/v1"
            os.environ["OPENAI_API_KEY"] = api_key
        elif tool == "claude":
            os.environ["ANTHROPIC_BASE_URL"] = base_url.rstrip("/") + "/llm"
            os.environ["ANTHROPIC_API_KEY"] = api_key
        else:
            os.environ["AIFLOW_BASE_URL"] = base_url
            os.environ["AIFLOW_API_KEY"] = api_key
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


class MockGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "success"
    model_ids = ("gpt-image-test",)
    response_payload: dict[str, object] = image_payload(declared_size="16x16")
    redirect_url = ""
    seen_authorization = ""
    seen_request: dict[str, object] | None = None
    get_count = 0
    post_count = 0

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def write_json(self, status: int, value: dict[str, object], *, request_id: str = "") -> None:
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        if request_id:
            self.send_header("X-Request-ID", request_id)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        type(self).get_count += 1
        type(self).seen_authorization = self.headers.get("Authorization", "")
        if type(self).mode == "redirect":
            self.send_response(302)
            self.send_header("Location", type(self).redirect_url)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        if self.path != "/llm/v1/models":
            self.write_json(404, {"error": {"code": "not_found"}})
            return
        if type(self).mode == "budget":
            self.write_json(
                402,
                {
                    "error": {
                        "code": "deny_budget_exceeded",
                        "message": "secret-upstream-body-marker",
                        "retry_safe": False,
                    }
                },
                request_id="aiflow_req_budget",
            )
            return
        self.write_json(200, models_payload(*type(self).model_ids), request_id="aiflow_req_models")

    def do_POST(self) -> None:
        type(self).post_count += 1
        type(self).seen_authorization = self.headers.get("Authorization", "")
        if self.path != "/llm/v1/images/generations":
            self.write_json(404, {"error": {"code": "not_found"}})
            return
        size = int(self.headers.get("Content-Length", "0"))
        type(self).seen_request = json.loads(self.rfile.read(size))
        self.write_json(200, type(self).response_payload, request_id="aiflow_req_generate")


class GatewayServer:
    def __init__(
        self,
        *,
        mode: str = "success",
        model_ids: tuple[str, ...] = ("gpt-image-test",),
        response_payload: dict[str, object] | None = None,
        redirect_url: str = "",
    ) -> None:
        self.mode = mode
        self.model_ids = model_ids
        self.response_payload = response_payload or image_payload(declared_size="16x16")
        self.redirect_url = redirect_url

    def __enter__(self) -> "GatewayServer":
        MockGatewayHandler.mode = self.mode
        MockGatewayHandler.model_ids = self.model_ids
        MockGatewayHandler.response_payload = self.response_payload
        MockGatewayHandler.redirect_url = self.redirect_url
        MockGatewayHandler.seen_authorization = ""
        MockGatewayHandler.seen_request = None
        MockGatewayHandler.get_count = 0
        MockGatewayHandler.post_count = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockGatewayHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class RedirectSinkHandler(BaseHTTPRequestHandler):
    seen_authorization = ""

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:
        type(self).seen_authorization = self.headers.get("Authorization", "")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


class RedirectSink:
    def __enter__(self) -> "RedirectSink":
        RedirectSinkHandler.seen_authorization = ""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectSinkHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/capture"
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class RuntimeTests(unittest.TestCase):
    def generate_request(self, root: Path, output: Path, **extra: object) -> Path:
        request = {"schema": runtime.REQUEST_SCHEMA, "prompt": "blue test card", "output": str(output), **extra}
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return request_path

    def test_normalize_gateway_base_accepts_origin_and_gateway_base(self) -> None:
        self.assertEqual(runtime.normalize_gateway_base("https://example.test"), "https://example.test/llm/v1")
        self.assertEqual(runtime.normalize_gateway_base("https://example.test/llm/v1/"), "https://example.test/llm/v1")
        self.assertEqual(runtime.normalize_gateway_base("https://example.test/llm"), "https://example.test/llm/v1")
        with self.assertRaises(runtime.ImageSkillError):
            runtime.normalize_gateway_base("http://example.test")
        with self.assertRaises(runtime.ImageSkillError):
            runtime.normalize_gateway_base("https://example.test/v1")

    def test_model_list_is_capability_only_and_selects_one_model(self) -> None:
        models = runtime.safe_models(models_payload("gpt-image-test"))
        self.assertEqual(models, [{"id": "gpt-image-test", "supports_image_generation": True}])
        self.assertNotIn("secret-route-marker", json.dumps(models))
        self.assertEqual(runtime.select_image_model(models, None, None), "gpt-image-test")

    def test_multiple_models_require_explicit_selection(self) -> None:
        models = runtime.safe_models(models_payload("image-a", "image-b"))
        with self.assertRaises(runtime.ImageSkillError) as caught:
            runtime.select_image_model(models, None, None)
        self.assertEqual(caught.exception.category, "model_selection_required")
        self.assertEqual(runtime.select_image_model(models, "image-b", None), "image-b")

    def test_models_command_uses_live_gateway_contract(self) -> None:
        with GatewayServer() as gateway, launcher_environment("pi", gateway.base_url, "secret-key-marker"):
            result = runtime.list_models(runtime.build_parser().parse_args(["models"]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["models"], [{"id": "gpt-image-test", "supports_image_generation": True}])
        self.assertNotIn("provider-internal-marker", json.dumps(result))
        self.assertEqual(MockGatewayHandler.seen_authorization, "Bearer secret-key-marker")

    def test_live_generation_saves_verified_artifact_and_provenance(self) -> None:
        with GatewayServer() as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result.png"
            request_path = self.generate_request(root, output)
            with launcher_environment("pi", gateway.base_url, "secret-key-marker"):
                args = runtime.build_parser().parse_args(["generate", "--request", str(request_path)])
                result = runtime.generate(args)
            self.assertTrue(result["ok"])
            self.assertEqual(result["canonical_model"], "gpt-image-test")
            self.assertEqual(result["artifact"]["width"], 16)
            self.assertEqual(output.read_bytes(), png_bytes())
            provenance = json.loads(Path(result["provenance_path"]).read_text(encoding="utf-8"))
            self.assertEqual(provenance["schema"], runtime.RESULT_SCHEMA)
            self.assertNotIn(base64.b64encode(png_bytes()).decode("ascii"), json.dumps(provenance))
            self.assertEqual(MockGatewayHandler.seen_authorization, "Bearer secret-key-marker")
            self.assertEqual(MockGatewayHandler.seen_request["n"], 1)

    def test_missing_returned_metadata_does_not_create_false_warning(self) -> None:
        response = image_payload()
        response.pop("quality", None)
        response.pop("output_format", None)
        with GatewayServer(response_payload=response) as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path = self.generate_request(root, root / "result.png", quality="high", output_format="png")
            with launcher_environment("pi", gateway.base_url, "key"):
                result = runtime.generate(runtime.build_parser().parse_args(["generate", "--request", str(request_path)]))
            self.assertEqual(result["warnings"], [])

    def test_output_extension_and_format_are_resolved_before_gateway_request(self) -> None:
        with GatewayServer() as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path = self.generate_request(root, root / "result.jpg", output_format="png")
            with launcher_environment("pi", gateway.base_url, "key"):
                with self.assertRaises(runtime.ImageSkillError) as caught:
                    runtime.generate(runtime.build_parser().parse_args(["generate", "--request", str(request_path)]))
            self.assertEqual(caught.exception.category, "input_error")
            self.assertEqual(MockGatewayHandler.get_count, 0)
            self.assertEqual(MockGatewayHandler.post_count, 0)

    def test_existing_output_is_rejected_before_any_gateway_request(self) -> None:
        with GatewayServer() as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result.png"
            output.write_bytes(b"existing")
            request_path = self.generate_request(root, output)
            with launcher_environment("pi", gateway.base_url, "key"):
                with self.assertRaises(runtime.ImageSkillError) as caught:
                    runtime.generate(runtime.build_parser().parse_args(["generate", "--request", str(request_path)]))
            self.assertEqual(caught.exception.category, "artifact_exists")
            self.assertEqual(MockGatewayHandler.get_count, 0)
            self.assertEqual(MockGatewayHandler.post_count, 0)

    def test_symlink_output_is_rejected_before_any_gateway_request(self) -> None:
        with GatewayServer() as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.png"
            output = root / "link.png"
            output.symlink_to(target)
            request_path = self.generate_request(root, output)
            with launcher_environment("pi", gateway.base_url, "key"):
                with self.assertRaises(runtime.ImageSkillError) as caught:
                    runtime.generate(runtime.build_parser().parse_args(["generate", "--request", str(request_path)]))
            self.assertEqual(caught.exception.category, "artifact_error")
            self.assertFalse(target.exists())
            self.assertEqual(MockGatewayHandler.get_count, 0)
            self.assertEqual(MockGatewayHandler.post_count, 0)

    def test_artifact_pair_rolls_back_sidecar_if_image_link_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.png"
            calls = 0
            real_link = os.link

            def fail_second_link(source: object, destination: object, *args: object, **kwargs: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated image link failure")
                real_link(source, destination, *args, **kwargs)

            with mock.patch.object(runtime.os, "link", side_effect=fail_second_link):
                with self.assertRaises(runtime.ImageSkillError) as caught:
                    runtime.write_artifacts(output, png_bytes(), {"schema": runtime.RESULT_SCHEMA})
            self.assertEqual(caught.exception.category, "artifact_error")
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".png.json").exists())

    def test_truncated_image_container_is_rejected(self) -> None:
        response = image_payload(declared_size="16x16")
        encoded = response["data"][0]["b64_json"]
        response["data"][0]["b64_json"] = base64.b64encode(base64.b64decode(encoded)[:-1]).decode("ascii")
        with self.assertRaises(runtime.ImageSkillError) as caught:
            runtime.decode_and_inspect_image(response, runtime.DEFAULT_MAX_IMAGE_BYTES)
        self.assertEqual(caught.exception.category, "invalid_gateway_response")

    def test_decompression_bomb_is_structured(self) -> None:
        response = image_payload(declared_size="16x16")
        with mock.patch("PIL.Image.open", side_effect=DecompressionBombError("too large")):
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.decode_and_inspect_image(response, runtime.DEFAULT_MAX_IMAGE_BYTES)
        self.assertEqual(caught.exception.category, "invalid_gateway_response")

    def test_image_dimensions_are_bounded_after_decode(self) -> None:
        response = image_payload(width=16, height=16, declared_size="16x16")
        with mock.patch.object(runtime, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.decode_and_inspect_image(response, runtime.DEFAULT_MAX_IMAGE_BYTES)
        self.assertEqual(caught.exception.category, "invalid_gateway_response")

    def test_mismatched_response_metadata_is_rejected_before_write(self) -> None:
        response = image_payload(declared_size="1024x1024")
        with GatewayServer(response_payload=response) as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result.png"
            request_path = self.generate_request(root, output)
            with launcher_environment("pi", gateway.base_url, "key"):
                with self.assertRaises(runtime.ImageSkillError) as caught:
                    runtime.generate(runtime.build_parser().parse_args(["generate", "--request", str(request_path)]))
            self.assertEqual(caught.exception.category, "invalid_gateway_response")
            self.assertFalse(output.exists())

    def test_codex_and_claude_launcher_contexts_are_strict(self) -> None:
        original = dict(os.environ)
        try:
            for key in LAUNCHER_KEYS:
                os.environ.pop(key, None)
            os.environ["AIFLOW_BASE_URL"] = "https://stale.example/llm/v1"
            os.environ["AIFLOW_API_KEY"] = "stale-key"
            os.environ["AIFLOW_TOOL"] = "codex"
            os.environ["OPENAI_BASE_URL"] = "https://gateway.example/llm/v1"
            os.environ["OPENAI_API_KEY"] = "codex-key"
            self.assertEqual(runtime.resolve_connection(), ("https://gateway.example/llm/v1", "codex-key"))
            os.environ.pop("OPENAI_API_KEY")
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.resolve_connection()
            self.assertEqual(caught.exception.details["required_environment"], ["OPENAI_API_KEY"])
            os.environ.pop("OPENAI_BASE_URL")
            os.environ["AIFLOW_TOOL"] = "claude"
            os.environ["ANTHROPIC_BASE_URL"] = "https://gateway.example/llm"
            os.environ["ANTHROPIC_API_KEY"] = "claude-key"
            self.assertEqual(runtime.resolve_connection(), ("https://gateway.example/llm/v1", "claude-key"))
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_generic_harness_does_not_consume_provider_named_credentials(self) -> None:
        original = dict(os.environ)
        try:
            for key in LAUNCHER_KEYS:
                os.environ.pop(key, None)
            os.environ["OPENAI_BASE_URL"] = "https://evil.example/llm/v1"
            os.environ["OPENAI_API_KEY"] = "must-not-forward"
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.resolve_connection()
            self.assertEqual(caught.exception.category, "configuration_error")
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_provider_direct_launcher_url_is_rejected(self) -> None:
        original = dict(os.environ)
        try:
            for key in LAUNCHER_KEYS:
                os.environ.pop(key, None)
            os.environ["AIFLOW_TOOL"] = "codex"
            os.environ["OPENAI_BASE_URL"] = "https://api.openai.example/v1"
            os.environ["OPENAI_API_KEY"] = "must-not-forward"
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.resolve_connection()
            self.assertEqual(caught.exception.category, "configuration_error")
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_redirect_is_not_followed_or_sent_authorization(self) -> None:
        with RedirectSink() as sink, GatewayServer(mode="redirect", redirect_url=sink.url) as gateway:
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.http_json(
                    runtime.normalize_gateway_base(gateway.base_url) + "/models",
                    "secret-key-marker",
                    timeout=2,
                    max_response_bytes=1024,
                )
            self.assertEqual(caught.exception.http_status, 302)
            self.assertEqual(RedirectSinkHandler.seen_authorization, "")

    def test_gateway_error_is_classified_without_raw_body(self) -> None:
        with GatewayServer(mode="budget") as gateway:
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.http_json(
                    runtime.normalize_gateway_base(gateway.base_url) + "/models",
                    "secret-key-marker",
                    timeout=2,
                    max_response_bytes=1024,
                )
            error = caught.exception.as_dict()
            self.assertEqual(error["category"], "budget_denied")
            self.assertEqual(error["code"], "deny_budget_exceeded")
            self.assertFalse(error["retry_safe"])
            self.assertEqual(error["request_id"], "aiflow_req_budget")
            self.assertNotIn("secret-upstream-body-marker", json.dumps(error))
            self.assertNotIn("secret-key-marker", json.dumps(error))

    def test_production_cli_has_no_fixture_injection_options(self) -> None:
        parser = runtime.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["models", "--input-json", "models.json"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["generate", "--request", "request.json", "--response-json", "response.json"])


if __name__ == "__main__":
    unittest.main()
