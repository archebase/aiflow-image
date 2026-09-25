# Runtime contract

Read this before the first call in a session. Everything below was verified against the live gateway on 2026-09-26.

## Verified gateway facts

| Item | Value |
|---|---|
| Gateway | `https://aiflow.archebase.ai/v1` (New API) |
| Credential | `ARCHEBASE_API_KEY` from the AIFlow token service |
| Base URL override | `AIFLOW_BASE_URL`; origin or `/v1` |
| Model discovery | authenticated `GET /v1/models` (advisory only — see below) |
| Image generation | authenticated `POST /v1/images/generations` |
| Default model | `gpt-image-2` |
| Models that generated successfully | `gpt-image-2`, `gpt-image-2.5` |
| Result transport | `data[0].b64_json` plus `data[0].generation_id` |
| Returned metadata | `size`, `quality`, `background`, `output_format`, `usage` |
| Size normalization | requested `1024x1024` returns `1254x1254`; returned values win |
| Image edit / reference input | not verified through this gateway |
| Streaming | not used by this skill |

### `supported_endpoint_types` is not a capability gate

`GET /v1/models` is a presentation list. Measured on 2026-09-26:

- `gpt-image-2` — `supported_endpoint_types: ["image-generation", ...]` → generates.
- `gpt-image-1.5` — image endpoint declared → listed.
- `gpt-image-2.5` — `supported_endpoint_types: []` → **generates successfully anyway** (HTTP 200, valid 1254×1254 PNG).

An empty list means the gateway's model record has no endpoint type registered; it does not mean the route is absent. Routing that makes 2.5 work is configured outside this listing. Therefore the skill treats the listing as a hint and lets the generation call decide. Do not reintroduce a hard gate on `supported_endpoint_types`.

The gateway is the source of truth. If the deployment changes, re-verify with `models` and a real generation call before editing this table.


## Command surface

```bash
python3 scripts/aiflow_image.py models
python3 scripts/aiflow_image.py generate --request request.json
```

Both commands emit JSON on stdout and exit non-zero on failure. Generation never retries automatically.

## Configuration

The runtime reads exactly two variables:

- `AIFLOW_BASE_URL` — optional; defaults to `https://aiflow.archebase.ai/v1`;
- `ARCHEBASE_API_KEY` — required; `AIFLOW_API_KEY` is accepted as a fallback.

Provider-named variables such as `OPENAI_*` or `ANTHROPIC_*` are never read. A URL with embedded credentials, query or fragment is rejected, non-local plain HTTP is rejected, and redirects are never followed. There is no endpoint or credential CLI flag, so a prompt cannot redirect the credential.

## Model selection

1. `model` from the request, passed through unchanged;
2. otherwise the default, `gpt-image-2`.

There is no capability pre-check against the listing, because the listing does not predict routing. If the gateway rejects a model, the real error is returned (`invalid_request`, `not_found`, `model_not_found`, …). Never rank models by name, and never substitute a different model silently.

## Request schema

`aiflow.image-request.v1`. Required:

- `prompt` — non-empty, at most 32,000 characters;
- `output` — path ending in `.png`, `.jpg`, `.jpeg` or `.webp`.

Optional: `model`, `size`, `quality`, `output_format`, `background`, `moderation`, `output_compression`, `overwrite`.

- `size` accepts `auto` or `WIDTHxHEIGHT` within the gateway contract (edges multiple of 16, ≤ 3840, ratio 1:3–3:1, 655,360–8,294,400 pixels).
- The output extension determines `output_format`; a conflicting explicit value is rejected before any request.
- `overwrite` defaults to `false`; an existing image or sidecar stops the command before any gateway call.
- `n` is always 1. Use separate requests for separate assets.

## Result and provenance

A successful run returns `aiflow.image-result.v1` and writes `<image-path>.json` containing canonical model, prompt, requested vs returned metadata, actual format/dimensions/mode/bytes/SHA-256, `request_id`, `generation_id`, safe usage and normalization warnings. It never contains the credential or the Base64 payload.

The bitmap is decoded, its container is validated, and Pillow fully loads it before the file is committed. Reported `size` and `output_format` must match the decoded image.

## Stable error categories

`authentication_failed`, `budget_denied`, `policy_denied`, `quota_exhausted`, `not_found`, `timeout`, `service_unavailable`, `invalid_request`, `model_unavailable`, `model_selection_required`, `no_image_model`, `network_error`, `invalid_gateway_response`, `artifact_exists`, `artifact_error`, `dependency_missing`, `configuration_error`, `cancelled_charge_unknown`.

Each error carries a category, a short safe message, and when available HTTP status, gateway code, request ID and explicit `retry_safe`. Raw gateway bodies and credentials never appear. Retry only when `retry_safe` is explicitly `true` and a human accepts the extra cost.
