#!/usr/bin/env python3
"""Generate images through the AIFlow token service (New API gateway).

The CLI reads its credential from the environment, discovers which models the
current token can actually use for image generation, performs one bounded
request, verifies the artifact and writes it with a provenance sidecar.
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

# Verified against the live gateway: https://aiflow.archebase.ai/v1
DEFAULT_BASE_URL = "https://aiflow.archebase.ai/v1"
BASE_URL_ENV = "AIFLOW_BASE_URL"
API_KEY_ENVS = ("ARCHEBASE_API_KEY", "AIFLOW_API_KEY")
IMAGE_ENDPOINT_TYPE = "image-generation"
DEFAULT_MODEL = "gpt-image-2"

DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_RESPONSE_BYTES = 192 * 1024 * 1024
DEFAULT_MAX_IMAGE_BYTES = 96 * 1024 * 1024
ERROR_BODY_LIMIT = 64 * 1024
MAX_IMAGE_EDGE = 4096
MAX_IMAGE_PIXELS = 16_777_216
FORMAT_EXTENSIONS = {"png": {".png"}, "jpeg": {".jpg", ".jpeg"}, "webp": {".webp"}}
PIL_FORMATS = {"png": "png", "jpeg": "jpeg", "jpg": "jpeg", "webp": "webp"}
RETURNED_METADATA = ("size", "quality", "background", "output_format")
USAGE_KEYS = ("input_tokens", "output_tokens", "total_tokens")


class ImageSkillError(Exception):
    """A stable, credential-safe error returned to the caller."""

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
        for key in ("code", "http_status", "retry_safe", "request_id"):
            item = getattr(self, key)
            if item is not None:
                value[key] = item
        if self.details:
            value["details"] = self.details
        return value


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the bearer credential never crosses an origin."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


HTTP_OPENER = urllib.request.build_opener(NoRedirectHandler())


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


def normalize_base_url(raw: str) -> str:
    """Accept the gateway origin or an explicit /v1 API base."""
    raw = (raw or "").strip()
    if not raw:
        return DEFAULT_BASE_URL
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ImageSkillError("configuration_error", f"{BASE_URL_ENV} must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ImageSkillError("configuration_error", f"{BASE_URL_ENV} must not contain credentials, query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ImageSkillError("configuration_error", "A non-local AIFlow gateway must use HTTPS")
    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = "/v1"
    elif path != "/v1":
        raise ImageSkillError("configuration_error", f"{BASE_URL_ENV} must be the gateway origin or end with /v1")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def resolve_connection() -> tuple[str, str]:
    """Resolve the gateway base URL and the token service credential."""
    base_url = normalize_base_url(os.environ.get(BASE_URL_ENV, "") or DEFAULT_BASE_URL)
    for name in API_KEY_ENVS:
        candidate = os.environ.get(name, "").strip()
        if candidate:
            return base_url, candidate
    raise ImageSkillError(
        "configuration_error",
        "No AIFlow credential found; export ARCHEBASE_API_KEY with a token from the AIFlow token service",
        details={"required_environment": [API_KEY_ENVS[0]]},
    )


def positive_number(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ImageSkillError("configuration_error", f"{name} must be a positive number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ImageSkillError("configuration_error", f"{name} must be a positive number")
    return parsed


def positive_integer(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ImageSkillError("configuration_error", f"{name} must be a positive integer") from error
    if parsed <= 0:
        raise ImageSkillError("configuration_error", f"{name} must be a positive integer")
    return parsed


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------


def request_id_from_headers(headers: Any) -> str | None:
    if headers is None:
        return None
    for name in ("X-Request-ID", "x-request-id", "X-Oneapi-Request-Id"):
        value = headers.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_error_body(body: bytes) -> tuple[str | None, str | None, bool | None]:
    """Return (code, message, retry_safe) from an OpenAI/New API error body."""
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, None
    if not isinstance(value, dict):
        return None, None, None
    error = value.get("error")
    if isinstance(error, str):
        return None, None, None
    if not isinstance(error, dict):
        return None, None, None
    code = error.get("code") if isinstance(error.get("code"), str) else None
    message = error.get("message") if isinstance(error.get("message"), str) else None
    retry_safe = error.get("retry_safe") if isinstance(error.get("retry_safe"), bool) else None
    return code, message, retry_safe


def gateway_error(status: int, body: bytes, headers: Any) -> ImageSkillError:
    code, message, retry_safe = parse_error_body(body)
    request_id = request_id_from_headers(headers)
    if status == 401:
        category, default_message = "authentication_failed", "The AIFlow gateway rejected the credential"
    elif status == 402:
        category, default_message = "budget_denied", "The request was denied by budget policy"
    elif status == 403:
        category, default_message = "policy_denied", "The token is not allowed to use this model or operation"
    elif status == 429:
        category, default_message = "quota_exhausted", "No image-generation capacity is currently available"
    elif status == 404:
        category, default_message = "not_found", "The AIFlow gateway does not expose this endpoint"
    elif status == 504:
        category, default_message = "timeout", "The AIFlow gateway timed out while generating the image"
    elif status in {500, 502, 503}:
        category, default_message = "service_unavailable", "The AIFlow gateway is temporarily unavailable"
    elif status == 400:
        category, default_message = "invalid_request", "The AIFlow gateway rejected the image request"
    else:
        category, default_message = "gateway_error", "The AIFlow gateway returned an unexpected error"
    # Gateway messages are short and useful; never include the raw body.
    safe_message = default_message
    if message and len(message) <= 300:
        safe_message = f"{default_message}: {message.strip()}"
    return ImageSkillError(
        category,
        safe_message,
        code=code,
        http_status=status,
        retry_safe=retry_safe,
        request_id=request_id,
    )


def _bounded_read(response: Any, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ImageSkillError("invalid_gateway_response", "The gateway response exceeded the configured size limit")
    return data


def request_json(
    url: str,
    api_key: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float,
    max_response_bytes: int,
) -> tuple[dict[str, Any], str | None]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with HTTP_OPENER.open(request, timeout=timeout) as response:
            raw = _bounded_read(response, max_response_bytes)
            request_id = request_id_from_headers(response.headers)
    except urllib.error.HTTPError as error:
        raise gateway_error(error.code, error.read(ERROR_BODY_LIMIT), error.headers) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ImageSkillError("network_error", "Could not reach the AIFlow gateway") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImageSkillError("invalid_gateway_response", "The AIFlow gateway returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ImageSkillError("invalid_gateway_response", "The AIFlow gateway returned a non-object JSON response")
    return value, request_id


# --------------------------------------------------------------------------
# model discovery
# --------------------------------------------------------------------------


def discover_models(payload: Any) -> list[dict[str, Any]]:
    """Return an advisory model list.

    `/v1/models` is a presentation list. `supported_endpoint_types` reflects the
    gateway's own record and does NOT prove whether a route works: measured on
    the live gateway, `gpt-image-2.5` reports an empty list yet generates
    successfully. The authoritative capability test is the generation call, so
    this listing is only a hint for choosing a model.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ImageSkillError("invalid_gateway_response", "The model list is not in the expected format")
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip() or model_id in seen:
            continue
        seen.add(model_id)
        endpoint_types = item.get("supported_endpoint_types")
        declared_image = isinstance(endpoint_types, list) and IMAGE_ENDPOINT_TYPE in endpoint_types
        models.append(
            {
                "id": model_id,
                "declared_image_endpoint": declared_image,
                "image_hint": declared_image or "image" in model_id.lower(),
            }
        )
    return models


def image_hints(models: list[dict[str, Any]]) -> list[str]:
    return [model["id"] for model in models if model.get("image_hint")]


def select_model(requested: str | None) -> str:
    """Choose the model to send. The gateway decides whether it actually works."""
    wanted = (requested or "").strip()
    return wanted or DEFAULT_MODEL


def load_models(
    base_url: str,
    api_key: str,
    *,
    timeout: float,
    max_response_bytes: int,
) -> tuple[list[dict[str, Any]], str | None]:
    payload, request_id = request_json(
        base_url + "/models",
        api_key,
        timeout=timeout,
        max_response_bytes=max_response_bytes,
    )
    return discover_models(payload), request_id


# --------------------------------------------------------------------------
# image validation
# --------------------------------------------------------------------------


def validate_container(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        position = 8
        while position + 12 <= len(content):
            length = int.from_bytes(content[position : position + 4], "big")
            chunk_type = content[position + 4 : position + 8]
            position += 12 + length
            if chunk_type == b"IEND":
                if length == 0 and position == len(content):
                    return "png"
                break
        raise ImageSkillError("invalid_gateway_response", "The gateway returned an incomplete PNG container")
    if content.startswith(b"\xff\xd8"):
        if content.endswith(b"\xff\xd9"):
            return "jpeg"
        raise ImageSkillError("invalid_gateway_response", "The gateway returned an incomplete JPEG container")
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        if int.from_bytes(content[4:8], "little") + 8 == len(content):
            return "webp"
        raise ImageSkillError("invalid_gateway_response", "The gateway returned an incomplete WebP container")
    raise ImageSkillError("invalid_gateway_response", "The gateway returned an unsupported image container")


def decode_image(response: Any, max_image_bytes: int) -> tuple[bytes, dict[str, Any], str | None]:
    data = response.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise ImageSkillError("invalid_gateway_response", "The response must contain exactly one image")
    item = data[0]
    encoded = item.get("b64_json")
    if not isinstance(encoded, str) or not encoded:
        raise ImageSkillError("invalid_gateway_response", "The response did not contain b64_json image data")
    if len(encoded) > ((max_image_bytes + 2) // 3) * 4 + 4:
        raise ImageSkillError("invalid_gateway_response", "The decoded image would exceed the configured size limit")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ImageSkillError("invalid_gateway_response", "The gateway returned invalid Base64 image data") from error
    if not content or len(content) > max_image_bytes:
        raise ImageSkillError("invalid_gateway_response", "The decoded image is empty or exceeds the size limit")
    container = validate_container(content)
    try:
        from PIL import Image, UnidentifiedImageError
        from PIL.Image import DecompressionBombError
    except ImportError as error:
        raise ImageSkillError("dependency_missing", "Pillow is required to verify image artifacts") from error
    try:
        from PIL import Image as _Image

        with _Image.open(BytesIO(content)) as image:
            actual_format = PIL_FORMATS.get((image.format or "").lower())
            if actual_format is None or actual_format != container:
                raise ImageSkillError("invalid_gateway_response", "The decoded image format is unsupported or inconsistent")
            if image.width <= 0 or image.height <= 0 or image.width > MAX_IMAGE_EDGE or image.height > MAX_IMAGE_EDGE:
                raise ImageSkillError("invalid_gateway_response", "The decoded image dimensions are outside the supported range")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ImageSkillError("invalid_gateway_response", "The decoded image exceeds the supported pixel count")
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
        raise ImageSkillError("invalid_gateway_response", "The gateway returned invalid image bytes") from error
    returned_format = response.get("output_format")
    if isinstance(returned_format, str) and returned_format != metadata["format"]:
        raise ImageSkillError("invalid_gateway_response", "The returned output_format does not match the decoded image")
    returned_size = response.get("size")
    actual_size = f"{metadata['width']}x{metadata['height']}"
    if isinstance(returned_size, str) and returned_size != actual_size:
        raise ImageSkillError("invalid_gateway_response", "The returned size does not match the decoded image")
    generation_id = item.get("generation_id") if isinstance(item.get("generation_id"), str) else None
    return content, metadata, generation_id


# --------------------------------------------------------------------------
# request handling
# --------------------------------------------------------------------------


def parse_size(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ImageSkillError("input_error", "size must be 'auto' or WIDTHxHEIGHT")
    value = value.strip()
    if value == "auto":
        return value
    match = re.fullmatch(r"([0-9]+)x([0-9]+)", value)
    if not match:
        raise ImageSkillError("input_error", "size must be 'auto' or WIDTHxHEIGHT")
    width, height = int(match.group(1)), int(match.group(2))
    if width % 16 or height % 16 or width > 3840 or height > 3840 or not (1 / 3 <= width / height <= 3):
        raise ImageSkillError("input_error", "size violates the gateway dimension contract")
    if not (655_360 <= width * height <= 8_294_400):
        raise ImageSkillError("input_error", "size violates the gateway pixel-count contract")
    return value


def validate_request(value: Any, output_override: Path | None) -> tuple[dict[str, Any], Path, bool]:
    """Build the gateway payload, resolve the output path and return overwrite intent."""
    if not isinstance(value, dict):
        raise ImageSkillError("input_error", "The image request must be a JSON object")
    schema = value.get("schema")
    if schema is not None and schema != REQUEST_SCHEMA:
        raise ImageSkillError("input_error", f"Unsupported request schema: {schema}")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ImageSkillError("input_error", "prompt is required")
    if len(prompt) > 32_000:
        raise ImageSkillError("input_error", "prompt exceeds the gateway 32,000 character limit")

    output_raw = output_override or value.get("output")
    if not isinstance(output_raw, (str, Path)) or not str(output_raw).strip():
        raise ImageSkillError("input_error", "output is required in the request or via --output")
    output = Path(output_raw).expanduser()
    if output.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ImageSkillError("input_error", "output must end with .png, .jpg, .jpeg or .webp")

    payload: dict[str, Any] = {"prompt": prompt, "n": 1}
    model = value.get("model")
    if model is not None:
        if not isinstance(model, str) or not model.strip():
            raise ImageSkillError("input_error", "model must be a non-empty string")
        payload["model"] = model.strip()
    size = parse_size(value.get("size"))
    if size is not None:
        payload["size"] = size
    for name, choices in (
        ("quality", {"auto", "low", "medium", "high"}),
        ("output_format", {"png", "jpeg", "webp"}),
        ("background", {"auto", "opaque", "transparent"}),
        ("moderation", {"auto", "low"}),
    ):
        selected = value.get(name)
        if selected is None:
            continue
        if not isinstance(selected, str) or selected not in choices:
            raise ImageSkillError("input_error", f"{name} must be one of: {', '.join(sorted(choices))}")
        payload[name] = selected
    extension_format = "jpeg" if output.suffix.lower() in {".jpg", ".jpeg"} else output.suffix.lower().lstrip(".")
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
    overwrite = value.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise ImageSkillError("input_error", "overwrite must be a boolean")
    return payload, output, overwrite


def artifact_paths(output: Path) -> tuple[Path, Path]:
    output = output.expanduser()
    if output.is_symlink():
        raise ImageSkillError("artifact_error", "Refusing to write an image through a symbolic link")
    manifest = output.with_suffix(output.suffix + ".json")
    if manifest.is_symlink():
        raise ImageSkillError("artifact_error", "Refusing to write provenance through a symbolic link")
    return output, manifest


def check_writable(output: Path, overwrite: bool) -> tuple[Path, Path]:
    output, manifest = artifact_paths(output)
    if not overwrite and (output.exists() or manifest.exists()):
        raise ImageSkillError(
            "artifact_exists",
            "The output image or provenance file already exists; pass overwrite=true or choose a new path",
        )
    return output, manifest


def _write_temp(parent: Path, prefix: str, content: bytes) -> Path:
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


def write_artifacts(output: Path, content: bytes, manifest: dict[str, Any], overwrite: bool) -> tuple[Path, Path]:
    output, manifest_path = check_writable(output, overwrite)
    parent = output.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ImageSkillError("artifact_error", "Could not create the output directory") from error
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    image_temp = _write_temp(parent, f".{output.name}.", content)
    manifest_temp = _write_temp(parent, f".{manifest_path.name}.", manifest_bytes)
    try:
        if overwrite:
            os.replace(image_temp, output)
            image_temp = Path()
            os.replace(manifest_temp, manifest_path)
            manifest_temp = Path()
        else:
            os.link(image_temp, output)
            os.link(manifest_temp, manifest_path)
        return output, manifest_path
    except FileExistsError as error:
        output.unlink(missing_ok=True)
        raise ImageSkillError("artifact_exists", "The output image or provenance file already exists") from error
    except OSError as error:
        output.unlink(missing_ok=True)
        raise ImageSkillError("artifact_error", "Could not save the image artifact") from error
    finally:
        for temp in (image_temp, manifest_temp):
            if str(temp) not in {"", "."}:
                temp.unlink(missing_ok=True)


def safe_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key in USAGE_KEYS:
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            result[key] = item
    for key in ("input_tokens_details", "output_tokens_details"):
        details = value.get(key)
        if isinstance(details, dict):
            clean = {
                name: item
                for name, item in details.items()
                if isinstance(item, int) and not isinstance(item, bool) and item >= 0
            }
            if clean:
                result[key] = clean
    return result or None


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def command_models(args: argparse.Namespace) -> dict[str, Any]:
    base_url, api_key = resolve_connection()
    timeout = positive_number(args.timeout, "timeout")
    max_response_bytes = positive_integer(args.max_response_bytes, "max_response_bytes")
    models, request_id = load_models(base_url, api_key, timeout=timeout, max_response_bytes=max_response_bytes)
    result: dict[str, Any] = {
        "schema": "aiflow.image-models.v1",
        "ok": True,
        "gateway": base_url,
        "default_model": select_model(None),
        "image_model_hints": image_hints(models),
        "models": models,
        "note": (
            "Advisory only. supported_endpoint_types does not prove a route works; "
            "the generation call is authoritative. A model may generate even when its "
            "declared endpoint list is empty."
        ),
    }
    if request_id:
        result["request_id"] = request_id
    return result


def command_generate(args: argparse.Namespace) -> dict[str, Any]:
    try:
        request_value = json.loads(args.request.read_text(encoding="utf-8"))
    except OSError as error:
        raise ImageSkillError("input_error", f"Could not read request file: {args.request}") from error
    except json.JSONDecodeError as error:
        raise ImageSkillError("input_error", f"Invalid JSON in request file: {args.request}") from error

    payload, output, overwrite = validate_request(request_value, args.output)
    check_writable(output, overwrite)

    base_url, api_key = resolve_connection()
    timeout = positive_number(args.timeout, "timeout")
    max_response_bytes = positive_integer(args.max_response_bytes, "max_response_bytes")
    max_image_bytes = positive_integer(args.max_image_bytes, "max_image_bytes")

    models, models_request_id = load_models(
        base_url, api_key, timeout=timeout, max_response_bytes=max_response_bytes
    )
    model = select_model(payload.get("model"))
    payload["model"] = model

    response, generate_request_id = request_json(
        base_url + "/images/generations",
        api_key,
        method="POST",
        payload=payload,
        timeout=timeout,
        max_response_bytes=max_response_bytes,
    )
    content, artifact, generation_id = decode_image(response, max_image_bytes)

    requested = {key: value for key, value in payload.items() if key != "prompt"}
    returned = {
        key: response[key] for key in RETURNED_METADATA if key in response and isinstance(response[key], str)
    }
    warnings: list[str] = []
    if returned.get("size") and requested.get("size") not in {None, "auto", returned["size"]}:
        warnings.append("requested_size_normalized")
    if returned.get("quality") and requested.get("quality") not in {None, "auto", returned["quality"]}:
        warnings.append("requested_quality_normalized")
    manifest: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gateway": base_url,
        "canonical_model": model,
        "prompt": payload["prompt"],
        "requested": requested,
        "returned": returned,
        "artifact": artifact,
        "source_result": "b64_json",
        "warnings": warnings,
    }
    for label, value in (
        ("request_id", generate_request_id or models_request_id),
        ("generation_id", generation_id),
    ):
        if value:
            manifest[label] = value
    usage = safe_usage(response.get("usage"))
    if usage:
        manifest["usage"] = usage

    saved, manifest_path = write_artifacts(output, content, manifest, overwrite)
    result = dict(manifest)
    result["ok"] = True
    result["artifact"] = {**artifact, "path": str(saved)}
    result["provenance_path"] = str(manifest_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    models = subparsers.add_parser("models", help="List image-generation models available to this token")
    models.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    models.add_argument("--max-response-bytes", type=int, default=DEFAULT_MAX_RESPONSE_BYTES)
    models.set_defaults(handler=command_models)

    generate = subparsers.add_parser("generate", help="Generate and save one verified image")
    generate.add_argument("--request", required=True, type=Path, help="JSON request file")
    generate.add_argument("--output", type=Path, help="Override request.output")
    generate.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    generate.add_argument("--max-response-bytes", type=int, default=DEFAULT_MAX_RESPONSE_BYTES)
    generate.add_argument("--max-image-bytes", type=int, default=DEFAULT_MAX_IMAGE_BYTES)
    generate.set_defaults(handler=command_generate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = args.handler(args)
    except ImageSkillError as error:
        print(json.dumps({"ok": False, "error": error.as_dict()}, ensure_ascii=False, indent=2))
        return 1
    except KeyboardInterrupt:
        error = ImageSkillError(
            "cancelled_charge_unknown",
            "The request was cancelled; confirm billing state before retrying",
            retry_safe=False,
        )
        print(json.dumps({"ok": False, "error": error.as_dict()}, ensure_ascii=False, indent=2))
        return 130
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
