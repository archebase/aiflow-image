#!/usr/bin/env python3
"""Portable AIFlow image discovery and generation CLI.

The CLI reads credentials only from the environment, emits structured JSON, never
retries automatically, and saves verified image artifacts atomically.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


REQUEST_SCHEMA = "aiflow.image-request.v1"
RESULT_SCHEMA = "aiflow.image-result.v1"
MODELS_SCHEMA = "aiflow.image-models.v1"
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_RESPONSE_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_IMAGE_BYTES = 96 * 1024 * 1024
MAX_IMAGE_EDGE = 3840
MAX_IMAGE_PIXELS = 8_294_400
ERROR_BODY_LIMIT = 64 * 1024
FORMAT_EXTENSIONS = {"png": {".png"}, "jpeg": {".jpg", ".jpeg"}, "webp": {".webp"}}
PIL_FORMATS = {"png": "png", "jpeg": "jpeg", "jpg": "jpeg", "webp": "webp"}


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so Authorization never crosses an HTTP origin boundary."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


HTTP_OPENER = urllib.request.build_opener(NoRedirectHandler())


class ImageSkillError(Exception):
    """A stable, secret-safe error returned to an agent harness."""

    def __init__(
        self,
        category: str,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        retry_safe: bool | None = None,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.code = code
        self.http_status = http_status
        self.retry_safe = retry_safe
        self.request_id = request_id
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"category": self.category, "message": self.message}
        if self.code:
            value["code"] = self.code
        if self.http_status is not None:
            value["http_status"] = self.http_status
        if self.retry_safe is not None:
            value["retry_safe"] = self.retry_safe
        if self.request_id:
            value["request_id"] = self.request_id
        if self.details:
            value["details"] = self.details
        return value


def read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as error:
        raise ImageSkillError("input_error", f"Could not read JSON file: {path}") from error
    except json.JSONDecodeError as error:
        raise ImageSkillError("input_error", f"Invalid JSON file: {path}") from error


def normalize_gateway_base(raw: str) -> str:
    """Accept an AIFlow origin or an explicit /llm/v1 gateway base."""
    raw = raw.strip()
    if not raw:
        raise ImageSkillError("configuration_error", "AIFLOW_BASE_URL is required")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ImageSkillError("configuration_error", "AIFLOW_BASE_URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ImageSkillError("configuration_error", "AIFLOW_BASE_URL must not contain credentials, query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ImageSkillError("configuration_error", "Non-local AIFlow gateways must use HTTPS")
    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = "/llm/v1"
    elif path == "/llm":
        path = "/llm/v1"
    elif path != "/llm/v1":
        raise ImageSkillError(
            "configuration_error",
            "The AIFlow base URL must be the gateway origin or end with /llm or /llm/v1",
        )
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def positive_number(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ImageSkillError("configuration_error", f"{name} must be a positive number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ImageSkillError("configuration_error", f"{name} must be a positive number")
    return parsed


def positive_integer(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ImageSkillError("configuration_error", f"{name} must be a positive integer") from error
    if parsed <= 0:
        raise ImageSkillError("configuration_error", f"{name} must be a positive integer")
    return parsed


def bounded_read(response: Any, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ImageSkillError("invalid_gateway_response", "AIFlow response exceeded the configured size limit")
    return data


def request_id_from_headers(headers: Any) -> str | None:
    if headers is None:
        return None
    for name in ("X-Request-ID", "x-request-id"):
        value = headers.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_error_body(body: bytes) -> tuple[str | None, bool | None]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(value, dict):
        return None, None
    error = value.get("error")
    if not isinstance(error, dict):
        return None, None
    code = error.get("code") if isinstance(error.get("code"), str) else None
    retry_safe = error.get("retry_safe") if isinstance(error.get("retry_safe"), bool) else None
    return code, retry_safe


def gateway_error(status: int, body: bytes, headers: Any) -> ImageSkillError:
    code, retry_safe = parse_error_body(body)
    request_id = request_id_from_headers(headers)
    if status == 401:
        category, message = "authentication_failed", "AIFlow rejected the active credential"
    elif status == 402:
        category, message = "budget_denied", "AIFlow denied the request before generation because of budget policy"
    elif status == 403:
        category, message = "policy_denied", "AIFlow denied the requested model or operation"
    elif status == 429:
        category, message = "quota_exhausted", "No image-generation capacity is currently available for this request"
    elif status == 502 and code == "no_active_route":
        category, message = "no_active_route", "AIFlow has no active route for the requested image model"
    elif status == 504:
        category, message = "timeout", "AIFlow timed out while generating the image"
    elif status in {502, 503}:
        category, message = "service_unavailable", "AIFlow image generation is temporarily unavailable"
    elif status == 400 and code == "unsupported_model":
        category, message = "unsupported_model", "The selected model does not support this image request"
    elif status == 400:
        category, message = "invalid_request", "AIFlow rejected the image request"
    else:
        category, message = "gateway_error", "AIFlow returned an unexpected error"
    return ImageSkillError(
        category,
        message,
        code=code,
        http_status=status,
        retry_safe=retry_safe,
        request_id=request_id,
    )


def http_json(
    url: str,
    api_key: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float,
    max_response_bytes: int,
) -> tuple[dict[str, Any], str | None]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with HTTP_OPENER.open(request, timeout=timeout) as response:
            body = bounded_read(response, max_response_bytes)
            request_id = request_id_from_headers(response.headers)
    except urllib.error.HTTPError as error:
        body = error.read(ERROR_BODY_LIMIT)
        raise gateway_error(error.code, body, error.headers) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ImageSkillError("network_error", "Could not reach the AIFlow gateway") from error
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImageSkillError("invalid_gateway_response", "AIFlow returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ImageSkillError("invalid_gateway_response", "AIFlow returned a non-object JSON response")
    return value, request_id


def safe_models(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ImageSkillError("invalid_gateway_response", "AIFlow returned an invalid model list")
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip() or model_id in seen:
            continue
        seen.add(model_id)
        models.append(
            {
                "id": model_id,
                "supports_image_generation": item.get("supports_image_generation") is True,
            }
        )
    return models


def select_image_model(models: list[dict[str, Any]], explicit: str | None, preferred: str | None) -> str:
    image_models = sorted(model["id"] for model in models if model.get("supports_image_generation") is True)
    requested = (explicit or "").strip()
    configured = (preferred or "").strip()
    if requested:
        if requested not in image_models:
            raise ImageSkillError(
                "model_unavailable",
                "The requested model is not currently visible as image-capable",
                details={"requested_model": requested, "available_image_models": image_models},
            )
        return requested
    if configured:
        if configured not in image_models:
            raise ImageSkillError(
                "model_unavailable",
                "AIFLOW_IMAGE_MODEL is not currently visible as image-capable",
                details={"configured_model": configured, "available_image_models": image_models},
            )
        return configured
    if len(image_models) == 1:
        return image_models[0]
    if not image_models:
        raise ImageSkillError("no_image_model", "No image-capable model is available to the active AIFlow identity")
    raise ImageSkillError(
        "model_selection_required",
        "More than one image-capable model is available; select one explicitly",
        details={"available_image_models": image_models},
    )


def validate_size(value: Any) -> str | None:
    if value is None:
        return None
    if value == "auto":
        return value
    if not isinstance(value, str):
        raise ImageSkillError("input_error", "size must be 'auto' or WIDTHxHEIGHT")
    match = re.fullmatch(r"([0-9]+)x([0-9]+)", value)
    if not match:
        raise ImageSkillError("input_error", "size must be 'auto' or WIDTHxHEIGHT")
    width, height = int(match.group(1)), int(match.group(2))
    pixels = width * height
    ratio = width / height
    if width % 16 or height % 16 or width > 3840 or height > 3840 or not (1 / 3 <= ratio <= 3):
        raise ImageSkillError("input_error", "size violates the AIFlow image dimension contract")
    if not (655_360 <= pixels <= 8_294_400):
        raise ImageSkillError("input_error", "size violates the AIFlow image pixel-count contract")
    return value


def optional_choice(request: dict[str, Any], name: str, choices: set[str]) -> str | None:
    value = request.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or value not in choices:
        raise ImageSkillError("input_error", f"{name} must be one of: {', '.join(sorted(choices))}")
    return value


def validate_request(value: Any, output_override: Path | None) -> tuple[dict[str, Any], Path]:
    if not isinstance(value, dict):
        raise ImageSkillError("input_error", "The image request must be a JSON object")
    schema = value.get("schema")
    if schema is not None and schema != REQUEST_SCHEMA:
        raise ImageSkillError("input_error", f"Unsupported request schema: {schema}")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ImageSkillError("input_error", "prompt is required")
    if len(prompt) > 32_000:
        raise ImageSkillError("input_error", "prompt exceeds the AIFlow 32,000 character limit")
    output_raw: str | Path | None = output_override or value.get("output")
    if not isinstance(output_raw, (str, Path)) or not str(output_raw).strip():
        raise ImageSkillError("input_error", "output is required in the request or --output")
    output = Path(output_raw).expanduser()
    if output.is_symlink():
        raise ImageSkillError("artifact_error", "Refusing to write an image through a symbolic link")
    if output.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ImageSkillError("input_error", "output must include a .png, .jpg, .jpeg or .webp extension")
    model = value.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ImageSkillError("input_error", "model must be a non-empty string")
    payload: dict[str, Any] = {"prompt": prompt, "n": 1}
    if model is not None:
        payload["model"] = model.strip()
    size = validate_size(value.get("size"))
    if size is not None:
        payload["size"] = size
    for name, choices in (
        ("quality", {"auto", "low", "medium", "high"}),
        ("output_format", {"png", "jpeg", "webp"}),
        ("background", {"auto", "opaque", "transparent"}),
        ("moderation", {"auto", "low"}),
    ):
        selected = optional_choice(value, name, choices)
        if selected is not None:
            payload[name] = selected
    extension_format = "jpeg" if output.suffix.lower() in {".jpg", ".jpeg"} else output.suffix.lower().removeprefix(".")
    if payload.get("output_format") is None:
        payload["output_format"] = extension_format
    elif payload["output_format"] != extension_format:
        raise ImageSkillError("input_error", "output_format must match the output file extension")
    compression = value.get("output_compression")
    if compression is not None:
        if isinstance(compression, bool) or not isinstance(compression, int) or not (0 <= compression <= 100):
            raise ImageSkillError("input_error", "output_compression must be an integer from 0 to 100")
        if payload.get("output_format") not in {"jpeg", "webp"}:
            raise ImageSkillError("input_error", "output_compression requires output_format jpeg or webp")
        payload["output_compression"] = compression
    if "overwrite" in value:
        raise ImageSkillError("input_error", "overwrite is not supported; choose a new output path")
    return payload, output


def resolve_connection() -> tuple[str, str]:
    """Resolve the AIFlow launcher environment without prompt-controlled endpoints."""
    by_kind = {
        "aiflow": (os.environ.get("AIFLOW_BASE_URL", ""), "AIFLOW_API_KEY", False),
        "codex": (os.environ.get("OPENAI_BASE_URL", ""), "OPENAI_API_KEY", True),
        "claude": (os.environ.get("ANTHROPIC_BASE_URL", ""), "ANTHROPIC_API_KEY", True),
    }
    tool = os.environ.get("AIFLOW_TOOL", "").strip().lower()
    order = {
        "codex": ("codex",),
        "claude": ("claude",),
        "pi": ("aiflow",),
    }.get(tool, ("aiflow",))
    candidates = [by_kind[kind] for kind in order]
    rejected: list[str] = []
    missing_keys: list[str] = []
    for raw_url, default_key_env, require_llm_path in candidates:
        if not raw_url:
            continue
        try:
            gateway = normalize_gateway_base(raw_url)
            raw_path = urllib.parse.urlsplit(raw_url).path.rstrip("/")
            if require_llm_path and raw_path not in {"/llm", "/llm/v1"}:
                raise ImageSkillError("configuration_error", "Harness provider URL is not an AIFlow /llm gateway")
        except ImageSkillError:
            rejected.append(default_key_env)
            continue
        key_env = default_key_env
        api_key = os.environ.get(key_env, "")
        if not api_key:
            missing_keys.append(key_env)
            continue
        return gateway, api_key
    if missing_keys:
        raise ImageSkillError(
            "configuration_error",
            "An AIFlow gateway was discovered but its matching launcher credential is missing",
            details={"required_environment": sorted(set(missing_keys))},
        )
    if rejected:
        raise ImageSkillError(
            "configuration_error",
            "Configured model-provider URLs are not AIFlow /llm gateway URLs; refusing to forward their credentials",
        )
    raise ImageSkillError(
        "configuration_error",
        "No AIFlow launcher environment was found; configure AIFLOW_BASE_URL/AIFLOW_API_KEY",
    )


def load_models(
    *,
    gateway: str,
    api_key: str,
    timeout: float,
    max_response_bytes: int,
) -> tuple[list[dict[str, Any]], str | None]:
    payload, request_id = http_json(
        gateway + "/models",
        api_key,
        timeout=timeout,
        max_response_bytes=max_response_bytes,
    )
    return safe_models(payload), request_id


def safe_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            result[key] = item
    details = value.get("input_tokens_details")
    if isinstance(details, dict):
        clean: dict[str, int] = {}
        for key in ("text_tokens", "image_tokens"):
            item = details.get(key)
            if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
                clean[key] = item
        if clean:
            result["input_tokens_details"] = clean
    return result or None


def validate_container_bytes(content: bytes) -> str:
    """Validate complete PNG/JPEG/WebP container boundaries before Pillow decode."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        position = 8
        saw_iend = False
        while position + 12 <= len(content):
            length = int.from_bytes(content[position : position + 4], "big")
            chunk_type = content[position + 4 : position + 8]
            chunk_end = position + 12 + length
            if chunk_end > len(content):
                break
            position = chunk_end
            if chunk_type == b"IEND":
                saw_iend = length == 0 and position == len(content)
                break
        if not saw_iend:
            raise ImageSkillError("invalid_gateway_response", "AIFlow returned an incomplete PNG container")
        return "png"
    if content.startswith(b"\xff\xd8"):
        if not content.endswith(b"\xff\xd9"):
            raise ImageSkillError("invalid_gateway_response", "AIFlow returned an incomplete JPEG container")
        return "jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        declared_length = int.from_bytes(content[4:8], "little") + 8
        if declared_length != len(content):
            raise ImageSkillError("invalid_gateway_response", "AIFlow returned an incomplete WebP container")
        return "webp"
    raise ImageSkillError("invalid_gateway_response", "AIFlow returned an unsupported image container")


def decode_and_inspect_image(response: Any, max_image_bytes: int) -> tuple[bytes, dict[str, Any]]:
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise ImageSkillError("invalid_gateway_response", "AIFlow must return exactly one image")
    encoded = data[0].get("b64_json")
    if not isinstance(encoded, str) or not encoded:
        raise ImageSkillError("invalid_gateway_response", "AIFlow response did not contain b64_json")
    if len(encoded) > ((max_image_bytes + 2) // 3) * 4 + 4:
        raise ImageSkillError("invalid_gateway_response", "Decoded image would exceed the configured size limit")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ImageSkillError("invalid_gateway_response", "AIFlow returned invalid Base64 image data") from error
    if not content or len(content) > max_image_bytes:
        raise ImageSkillError("invalid_gateway_response", "Decoded image violated the configured size limit")
    container_format = validate_container_bytes(content)
    try:
        from PIL import Image, UnidentifiedImageError
        from PIL.Image import DecompressionBombError
    except ImportError as error:
        raise ImageSkillError("dependency_missing", "Pillow is required to validate image artifacts") from error
    try:
        with Image.open(BytesIO(content)) as candidate:
            candidate.verify()
        with Image.open(BytesIO(content)) as image:
            actual_format = PIL_FORMATS.get((image.format or "").lower())
            if actual_format is None or actual_format != container_format:
                raise ImageSkillError("invalid_gateway_response", "AIFlow returned an unsupported or inconsistent image format")
            if image.width <= 0 or image.height <= 0 or image.width > MAX_IMAGE_EDGE or image.height > MAX_IMAGE_EDGE:
                raise ImageSkillError("invalid_gateway_response", "AIFlow returned image dimensions outside the supported limit")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ImageSkillError("invalid_gateway_response", "AIFlow returned an image exceeding the supported pixel limit")
            image.load()
            metadata = {
                "format": actual_format,
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
    except (UnidentifiedImageError, DecompressionBombError, OSError, SyntaxError, ValueError) as error:
        raise ImageSkillError("invalid_gateway_response", "AIFlow returned invalid image bytes") from error
    returned_format = response.get("output_format")
    if returned_format is not None and returned_format != metadata["format"]:
        raise ImageSkillError("invalid_gateway_response", "AIFlow output_format did not match the decoded image")
    returned_size = response.get("size")
    actual_size = f"{metadata['width']}x{metadata['height']}"
    if returned_size is not None and returned_size != actual_size:
        raise ImageSkillError("invalid_gateway_response", "AIFlow size metadata did not match the decoded image")
    return content, metadata


def require_matching_extension(path: Path, actual_format: str) -> Path:
    if path.suffix.lower() not in FORMAT_EXTENSIONS[actual_format]:
        raise ImageSkillError(
            "artifact_error",
            f"Output extension {path.suffix} does not match decoded {actual_format} image",
        )
    return path


def write_temp(parent: Path, prefix: str, content: bytes) -> Path:
    handle = tempfile.NamedTemporaryFile(dir=parent, prefix=prefix, suffix=".tmp", delete=False)
    path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def artifact_paths(output: Path) -> tuple[Path, Path]:
    output = output.expanduser()
    if output.is_symlink():
        raise ImageSkillError("artifact_error", "Refusing to write an image through a symbolic link")
    manifest_path = output.with_suffix(output.suffix + ".json")
    if manifest_path.is_symlink():
        raise ImageSkillError("artifact_error", "Refusing to write provenance through a symbolic link")
    return output.resolve(strict=False), manifest_path.resolve(strict=False)


def preflight_artifact_paths(output: Path) -> tuple[Path, Path]:
    output, manifest_path = artifact_paths(output)
    if output.exists() or manifest_path.exists():
        raise ImageSkillError("artifact_exists", "Output image or provenance file already exists")
    return output, manifest_path


def write_artifacts(output: Path, content: bytes, manifest: dict[str, Any]) -> tuple[Path, Path]:
    output, manifest_path = preflight_artifact_paths(output)
    parent = output.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ImageSkillError("artifact_error", "Could not create the output directory") from error
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    image_temp = write_temp(parent, f".{output.name}.", content)
    manifest_temp = write_temp(parent, f".{manifest_path.name}.", manifest_bytes)
    manifest_created = False
    try:
        os.link(manifest_temp, manifest_path)
        manifest_created = True
        os.link(image_temp, output)
        return output, manifest_path
    except FileExistsError as error:
        if manifest_created:
            manifest_path.unlink(missing_ok=True)
        raise ImageSkillError("artifact_exists", "Output image or provenance file already exists") from error
    except OSError as error:
        if manifest_created:
            manifest_path.unlink(missing_ok=True)
        raise ImageSkillError("artifact_error", "Could not commit the image artifact pair") from error
    except BaseException:
        if manifest_created:
            manifest_path.unlink(missing_ok=True)
        raise
    finally:
        if str(image_temp) not in {"", "."}:
            image_temp.unlink(missing_ok=True)
        if str(manifest_temp) not in {"", "."}:
            manifest_temp.unlink(missing_ok=True)


def generate(args: argparse.Namespace) -> dict[str, Any]:
    request_value = read_json(args.request)
    payload, output = validate_request(request_value, args.output)
    preflight_artifact_paths(output)
    timeout = positive_number(str(args.timeout), "timeout")
    max_response_bytes = positive_integer(str(args.max_response_bytes), "max_response_bytes")
    max_image_bytes = positive_integer(str(args.max_image_bytes), "max_image_bytes")
    gateway, api_key = resolve_connection()
    models, model_request_id = load_models(
        gateway=gateway,
        api_key=api_key,
        timeout=timeout,
        max_response_bytes=max_response_bytes,
    )
    model = select_image_model(models, payload.get("model"), os.environ.get("AIFLOW_IMAGE_MODEL"))
    payload["model"] = model
    response, generation_request_id = http_json(
        gateway + "/images/generations",
        api_key,
        method="POST",
        payload=payload,
        timeout=timeout,
        max_response_bytes=max_response_bytes,
    )
    content, actual = decode_and_inspect_image(response, max_image_bytes)
    output = require_matching_extension(output, actual["format"])
    requested = {key: payload[key] for key in payload if key != "prompt"}
    returned = {
        key: response[key]
        for key in ("size", "quality", "background", "output_format")
        if isinstance(response, dict) and key in response
    }
    warnings: list[str] = []
    if returned.get("size") is not None and payload.get("size") not in {None, "auto", returned["size"]}:
        warnings.append("requested_size_normalized")
    if returned.get("quality") is not None and payload.get("quality") not in {None, "auto", returned["quality"]}:
        warnings.append("requested_quality_normalized")
    if returned.get("output_format") is not None and payload.get("output_format") not in {None, returned["output_format"]}:
        warnings.append("requested_output_format_normalized")
    manifest: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": "aiflow",
        "canonical_model": model,
        "prompt": payload["prompt"],
        "requested": requested,
        "returned": returned,
        "artifact": actual,
        "source_result": "b64_json",
        "warnings": warnings,
    }
    request_id = generation_request_id or model_request_id
    if request_id:
        manifest["request_id"] = request_id
    usage = safe_usage(response.get("usage") if isinstance(response, dict) else None)
    if usage:
        manifest["usage"] = usage
    output, manifest_path = write_artifacts(output, content, manifest)
    result = dict(manifest)
    result["ok"] = True
    result["artifact"] = {**actual, "path": str(output)}
    result["provenance_path"] = str(manifest_path)
    return result


def list_models(args: argparse.Namespace) -> dict[str, Any]:
    timeout = positive_number(str(args.timeout), "timeout")
    max_response_bytes = positive_integer(str(args.max_response_bytes), "max_response_bytes")
    gateway, api_key = resolve_connection()
    models, request_id = load_models(
        gateway=gateway,
        api_key=api_key,
        timeout=timeout,
        max_response_bytes=max_response_bytes,
    )
    result: dict[str, Any] = {"schema": MODELS_SCHEMA, "ok": True, "models": models}
    if request_id:
        result["request_id"] = request_id
    return result


def add_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-response-bytes", type=int, default=DEFAULT_MAX_RESPONSE_BYTES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    models = subparsers.add_parser("models", help="List safe canonical model capabilities")
    add_connection_arguments(models)
    models.set_defaults(handler=list_models)
    generation = subparsers.add_parser("generate", help="Generate and save one verified image")
    add_connection_arguments(generation)
    generation.add_argument("--request", required=True, type=Path, help="JSON request file")
    generation.add_argument("--output", type=Path, help="Override request.output")
    generation.add_argument("--max-image-bytes", type=int, default=DEFAULT_MAX_IMAGE_BYTES)
    generation.set_defaults(handler=generate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except ImageSkillError as error:
        print(json.dumps({"schema": RESULT_SCHEMA, "ok": False, "error": error.as_dict()}, ensure_ascii=False))
        return 1
    except KeyboardInterrupt:
        error = ImageSkillError(
            "cancelled_charge_unknown",
            "The request was cancelled; confirm AIFlow billing state before retrying",
            retry_safe=False,
        )
        print(json.dumps({"schema": RESULT_SCHEMA, "ok": False, "error": error.as_dict()}, ensure_ascii=False))
        return 130
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
