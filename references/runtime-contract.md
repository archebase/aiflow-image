# Runtime contract

Read this before the first gateway call in a session.

## Ownership boundary

AIFlow owns credentials, canonical models, authorization, route availability, provider selection, budgets, billing and retry safety. The skill owns request compilation, safe invocation, artifact verification and delivery. A harness only launches the same CLI; it does not reimplement AIFlow logic.

## Command surface

```bash
python3 scripts/aiflow_image.py models
python3 scripts/aiflow_image.py generate --request request.json
```

Both commands emit JSON to stdout and use a non-zero exit code on failure. Generation performs no automatic retry.

## Service configuration

The runtime reads exactly two variables from the AIFlow service environment:

- `AIFLOW_BASE_URL`;
- `AIFLOW_API_KEY`.

Both must be present together. The runtime never reads provider-named variables such as `OPENAI_*` or `ANTHROPIC_*`, and never treats them as AIFlow credentials. AIFlow's own machine-readable service documentation (for example its `llms.txt`) is the source of truth for how a deployment is configured; do not infer configuration from retired local-tool launchers.

`AIFLOW_BASE_URL` accepts the AIFlow origin, `/llm`, or `/llm/v1`. A non-local HTTP URL, a provider `/v1` URL or a URL containing credentials/query/fragment is rejected, and HTTP redirects are never followed. The CLI has no endpoint or credential override arguments; prompts cannot redirect the configured credential. The operator remains responsible for supplying the trusted AIFlow hostname.

## Model discovery and selection

The CLI calls authenticated `GET /llm/v1/models` and exposes only:

```json
{
  "id": "canonical-model-id",
  "supports_image_generation": true
}
```

Provider ownership, physical routes and account metadata are not forwarded. Image capability requires `supports_image_generation=true` from AIFlow.

Selection order:

1. request `model`;
2. `AIFLOW_IMAGE_MODEL`;
3. the only visible image-capable model;
4. otherwise fail with `model_selection_required` and list safe canonical IDs.

Do not rank model names lexically or keep a static “latest model” in this skill.

## Request schema

Use `aiflow.image-request.v1`. Required fields:

- `prompt`: non-empty string, at most 32,000 characters;
- `output`: local image path including `.png`, `.jpg`, `.jpeg` or `.webp`, unless `--output` overrides it.

Optional fields:

- `model`;
- `size`: `auto` or an AIFlow-valid `WIDTHxHEIGHT`;
- `quality`: `auto`, `low`, `medium`, `high`;
- `output_format`: `png`, `jpeg`, `webp`;
- `background`: `auto`, `opaque`, `transparent` (the selected model may reject unsupported values);
- `moderation`: `auto`, `low`;
- `output_compression`: 0–100 for JPEG/WebP.

The runtime never overwrites an image or sidecar. Choose a new versioned output path for every generation.

The runtime always sends `n=1`. Use separate requests for separate assets.

## Result and provenance

A successful command returns `aiflow.image-result.v1` and writes a sidecar at `<image-path>.json`. It records:

- canonical model and prompt;
- requested versus returned metadata;
- actual decoded format, dimensions, mode, bytes and SHA-256;
- request ID and safe usage when provided;
- normalization warnings;
- source transport (`b64_json`), never the Base64 payload.

The bitmap is decoded, fully verified with Pillow and matched against returned format/size metadata before any final path is created. Existing image or provenance paths are always refused.

## Stable error categories

Errors contain a category, safe message and, when available, HTTP status, gateway code, request ID and explicit `retry_safe` value. Important categories include:

- `authentication_failed`;
- `budget_denied`;
- `policy_denied`;
- `quota_exhausted`;
- `no_active_route`;
- `unsupported_model`;
- `model_selection_required`;
- `network_error`;
- `invalid_gateway_response`;
- `artifact_exists`;
- `cancelled_charge_unknown`.

Raw gateway bodies, credentials and Base64 data never appear in the result. Only retry when `retry_safe` is explicitly true and another charge is acceptable.
