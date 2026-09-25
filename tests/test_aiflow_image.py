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


CONFIG_KEYS = (
    "AIFLOW_BASE_URL",
    "ARCHEBASE_API_KEY",
    "AIFLOW_API_KEY",
)


def png_bytes(width: int = 64, height: int = 64) -> bytes:
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
                "owned_by": "newapi",
                "supported_endpoint_types": ["image-generation", "openai"],
            }
            for model_id in model_ids
        ],
    }


def image_payload(
    *,
    width: int = 1254,
    height: int = 1254,
    returned_size: str | None = None,
    generation_id: str = "gen_test",
) -> dict[str, object]:
    return {
        "created": 1790364360,
        "data": [
            {
                "b64_json": base64.b64encode(png_bytes(width, height)).decode("ascii"),
                "generation_id": generation_id,
            }
        ],
        "output_format": "png",
        "quality": "low",
        "background": "opaque",
        "size": returned_size or f"{width}x{height}",
        "usage": {"input_tokens": 16, "output_tokens": 515, "total_tokens": 531},
    }


@contextlib.contextmanager
def gateway_environment(base_url: str, api_key: str):
    original = dict(os.environ)
    try:
        for key in CONFIG_KEYS:
            os.environ.pop(key, None)
        if base_url:
            os.environ["AIFLOW_BASE_URL"] = base_url
        if api_key:
            os.environ["ARCHEBASE_API_KEY"] = api_key
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


class MockGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "success"
    model_ids: tuple[str, ...] = ("gpt-image-2",)
    response_payload: dict[str, object] = image_payload()
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
        if self.path != "/v1/models":
            self.write_json(404, {"error": {"code": "not_found"}})
            return
        if type(self).mode == "budget":
            self.write_json(
                402,
                {"error": {"code": "insufficient_quota", "message": "quota exceeded", "retry_safe": False}},
                request_id="aiflow_req_budget",
            )
            return
        if type(self).mode == "malformed":
            self.write_json(200, {"unexpected": True})
            return
        self.write_json(200, models_payload(*type(self).model_ids), request_id="aiflow_req_models")

    def do_POST(self) -> None:
        type(self).post_count += 1
        type(self).seen_authorization = self.headers.get("Authorization", "")
        if self.path != "/v1/images/generations":
            self.write_json(404, {"error": {"code": "not_found"}})
            return
        length = int(self.headers.get("Content-Length", "0"))
        type(self).seen_request = json.loads(self.rfile.read(length))
        self.write_json(200, type(self).response_payload, request_id="aiflow_req_generate")


class GatewayServer:
    def __init__(
        self,
        *,
        mode: str = "success",
        model_ids: tuple[str, ...] = ("gpt-image-2",),
        response_payload: dict[str, object] | None = None,
        redirect_url: str = "",
    ) -> None:
        self.mode = mode
        self.model_ids = model_ids
        self.response_payload = response_payload or image_payload()
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
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
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
    def write_request(self, root: Path, output: Path, **extra: object) -> Path:
        request = {"schema": runtime.REQUEST_SCHEMA, "prompt": "a blue circle", "output": str(output), **extra}
        path = root / "request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        return path

    # -- configuration -----------------------------------------------------

    def test_default_gateway_and_archebase_credential(self) -> None:
        with gateway_environment("", "service-key"):
            self.assertEqual(runtime.resolve_connection(), (runtime.DEFAULT_BASE_URL, "service-key"))

    def test_base_url_accepts_origin_or_v1(self) -> None:
        self.assertEqual(runtime.normalize_base_url("https://aiflow.archebase.ai"), "https://aiflow.archebase.ai/v1")
        self.assertEqual(
            runtime.normalize_base_url("https://aiflow.archebase.ai/v1/"), "https://aiflow.archebase.ai/v1"
        )
        with self.assertRaises(runtime.ImageSkillError):
            runtime.normalize_base_url("https://aiflow.archebase.ai/llm/v1")
        with self.assertRaises(runtime.ImageSkillError):
            runtime.normalize_base_url("http://aiflow.archebase.ai")

    def test_missing_credential_is_reported_with_the_env_name(self) -> None:
        with gateway_environment("", ""):
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.resolve_connection()
        self.assertEqual(caught.exception.category, "configuration_error")
        self.assertEqual(caught.exception.details["required_environment"], ["ARCHEBASE_API_KEY"])

    def test_aiflow_api_key_is_an_accepted_fallback(self) -> None:
        original = dict(os.environ)
        try:
            for key in CONFIG_KEYS:
                os.environ.pop(key, None)
            os.environ["AIFLOW_API_KEY"] = "fallback-key"
            self.assertEqual(runtime.resolve_connection(), (runtime.DEFAULT_BASE_URL, "fallback-key"))
        finally:
            os.environ.clear()
            os.environ.update(original)

    # -- discovery ---------------------------------------------------------

    def test_model_listing_is_advisory_not_a_capability_gate(self) -> None:
        payload = {
            "data": [
                {"id": "gpt-image-1.5", "supported_endpoint_types": ["image-generation", "openai"]},
                {"id": "gpt-image-2", "supported_endpoint_types": ["image-generation"]},
                {"id": "gpt-image-2.5", "supported_endpoint_types": []},
                {"id": "glm-5.3", "supported_endpoint_types": ["openai"]},
            ]
        }
        by_id = {m["id"]: m for m in runtime.discover_models(payload)}
        self.assertTrue(by_id["gpt-image-2"]["declared_image_endpoint"])
        self.assertFalse(by_id["gpt-image-2.5"]["declared_image_endpoint"])
        self.assertTrue(by_id["gpt-image-2.5"]["image_hint"])
        self.assertFalse(by_id["glm-5.3"]["image_hint"])

    def test_empty_endpoint_list_does_not_block_generation(self) -> None:
        # Measured on the live gateway: gpt-image-2.5 declares no endpoint yet generates.
        self.assertEqual(runtime.select_model("gpt-image-2.5"), "gpt-image-2.5")

    def test_default_model_is_gpt_image_2(self) -> None:
        self.assertEqual(runtime.select_model(None), "gpt-image-2")

    def test_models_command_reports_gateway_and_hints(self) -> None:
        with GatewayServer(model_ids=("gpt-image-1.5", "gpt-image-2", "glm-5.3")) as gateway:
            with gateway_environment(gateway.base_url, "secret-key"):
                result = runtime.command_models(runtime.build_parser().parse_args(["models"]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["default_model"], "gpt-image-2")
        self.assertIn("gpt-image-2", result["image_model_hints"])
        self.assertEqual(MockGatewayHandler.seen_authorization, "Bearer secret-key")

    # -- generation --------------------------------------------------------

    def test_generate_saves_verified_artifact_and_provenance(self) -> None:
        with GatewayServer() as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result.png"
            request = self.write_request(root, output, size="1024x1024", quality="low")
            with gateway_environment(gateway.base_url, "secret-key"):
                result = runtime.command_generate(
                    runtime.build_parser().parse_args(["generate", "--request", str(request)])
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["canonical_model"], "gpt-image-2")
            self.assertEqual(result["generation_id"], "gen_test")
            self.assertEqual(result["artifact"]["width"], 1254)
            self.assertEqual(MockGatewayHandler.seen_request["n"], 1)
            self.assertEqual(MockGatewayHandler.seen_request["model"], "gpt-image-2")
            provenance = json.loads(Path(result["provenance_path"]).read_text(encoding="utf-8"))
            self.assertEqual(provenance["schema"], runtime.RESULT_SCHEMA)
            self.assertEqual(provenance["artifact"]["sha256"], result["artifact"]["sha256"])
            self.assertNotIn(base64.b64encode(png_bytes()).decode("ascii"), json.dumps(provenance))

    def test_normalized_size_is_recorded_as_a_warning(self) -> None:
        with GatewayServer() as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = self.write_request(root, root / "result.png", size="1024x1024")
            with gateway_environment(gateway.base_url, "key"):
                result = runtime.command_generate(
                    runtime.build_parser().parse_args(["generate", "--request", str(request)])
                )
        self.assertEqual(result["requested"]["size"], "1024x1024")
        self.assertEqual(result["returned"]["size"], "1254x1254")
        self.assertIn("requested_size_normalized", result["warnings"])

    def test_existing_output_is_rejected_before_any_request(self) -> None:
        with GatewayServer() as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result.png"
            output.write_bytes(b"existing")
            request = self.write_request(root, output)
            with gateway_environment(gateway.base_url, "key"):
                with self.assertRaises(runtime.ImageSkillError) as caught:
                    runtime.command_generate(
                        runtime.build_parser().parse_args(["generate", "--request", str(request)])
                    )
        self.assertEqual(caught.exception.category, "artifact_exists")
        self.assertEqual(MockGatewayHandler.get_count, 0)
        self.assertEqual(MockGatewayHandler.post_count, 0)

    def test_overwrite_true_replaces_the_artifact(self) -> None:
        with GatewayServer() as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result.png"
            output.write_bytes(b"old")
            request = self.write_request(root, output, overwrite=True)
            with gateway_environment(gateway.base_url, "key"):
                result = runtime.command_generate(
                    runtime.build_parser().parse_args(["generate", "--request", str(request)])
                )
            self.assertTrue(result["ok"])
            self.assertNotEqual(output.read_bytes(), b"old")

    def test_symlink_output_is_rejected_before_any_request(self) -> None:
        with GatewayServer() as gateway, tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.png"
            link = root / "link.png"
            link.symlink_to(target)
            request = self.write_request(root, link)
            with gateway_environment(gateway.base_url, "key"):
                with self.assertRaises(runtime.ImageSkillError) as caught:
                    runtime.command_generate(
                        runtime.build_parser().parse_args(["generate", "--request", str(request)])
                    )
        self.assertEqual(caught.exception.category, "artifact_error")
        self.assertFalse(target.exists())
        self.assertEqual(MockGatewayHandler.post_count, 0)

    def test_output_extension_must_match_output_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = self.write_request(root, root / "result.jpg", output_format="png")
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.validate_request(json.loads(request.read_text()), None)
        self.assertEqual(caught.exception.category, "input_error")

    # -- artifact integrity ------------------------------------------------

    def test_truncated_container_is_rejected(self) -> None:
        payload = image_payload()
        encoded = payload["data"][0]["b64_json"]
        payload["data"][0]["b64_json"] = base64.b64encode(base64.b64decode(encoded)[:-1]).decode("ascii")
        with self.assertRaises(runtime.ImageSkillError) as caught:
            runtime.decode_image(payload, runtime.DEFAULT_MAX_IMAGE_BYTES)
        self.assertEqual(caught.exception.category, "invalid_gateway_response")

    def test_decompression_bomb_is_structured(self) -> None:
        with mock.patch("PIL.Image.open", side_effect=DecompressionBombError("too large")):
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.decode_image(image_payload(), runtime.DEFAULT_MAX_IMAGE_BYTES)
        self.assertEqual(caught.exception.category, "invalid_gateway_response")

    def test_returned_size_mismatch_is_rejected(self) -> None:
        payload = image_payload(width=64, height=64, returned_size="1024x1024")
        with self.assertRaises(runtime.ImageSkillError) as caught:
            runtime.decode_image(payload, runtime.DEFAULT_MAX_IMAGE_BYTES)
        self.assertEqual(caught.exception.category, "invalid_gateway_response")

    def test_pixel_limit_is_enforced(self) -> None:
        with mock.patch.object(runtime, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.decode_image(image_payload(width=64, height=64), runtime.DEFAULT_MAX_IMAGE_BYTES)
        self.assertEqual(caught.exception.category, "invalid_gateway_response")

    # -- transport safety --------------------------------------------------

    def test_redirect_is_not_followed(self) -> None:
        with RedirectSink() as sink, GatewayServer(mode="redirect", redirect_url=sink.url) as gateway:
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.request_json(gateway.base_url + "/models", "secret-key", timeout=2, max_response_bytes=1024)
        self.assertEqual(caught.exception.http_status, 302)
        self.assertEqual(RedirectSinkHandler.seen_authorization, "")

    def test_budget_error_is_classified_without_raw_body(self) -> None:
        with GatewayServer(mode="budget") as gateway:
            with self.assertRaises(runtime.ImageSkillError) as caught:
                runtime.request_json(gateway.base_url + "/models", "secret-key", timeout=2, max_response_bytes=1024)
        error = caught.exception.as_dict()
        self.assertEqual(error["category"], "budget_denied")
        self.assertEqual(error["http_status"], 402)
        self.assertEqual(error["request_id"], "aiflow_req_budget")

    def test_malformed_model_list_is_rejected(self) -> None:
        with GatewayServer(mode="malformed") as gateway:
            with gateway_environment(gateway.base_url, "key"):
                with self.assertRaises(runtime.ImageSkillError) as caught:
                    runtime.command_models(runtime.build_parser().parse_args(["models"]))
        self.assertEqual(caught.exception.category, "invalid_gateway_response")

    def test_cli_reports_errors_as_json(self) -> None:
        with gateway_environment("", ""):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                with mock.patch.object(sys, "argv", ["aiflow_image.py", "models"]):
                    code = runtime.main()
        self.assertEqual(code, 1)
        payload = json.loads(buffer.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["category"], "configuration_error")


if __name__ == "__main__":
    unittest.main()
