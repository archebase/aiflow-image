# ADR-0001: Consolidate AIFlow image generation into one portable skill

- Status: Accepted
- Date: 2026-09-26

## Context

The current implementation is split across two repositories:

- `aiflow-basic` performs live model discovery and one non-streaming Images request.
- `aiflow-image-production` contains production methodology, review guidance, crop utilities and release templates, but delegates all generation to `aiflow-basic`.

That split follows implementation primitives rather than user intent. A user installs an image-generation skill to produce image artifacts; model discovery and gateway transport are internal steps. Requiring a second skill creates an incomplete installation state and prevents the production skill from offering one stable executable contract to different agent harnesses.

The current repositories also disagree about gateway paths, credential names and model versions. The authoritative AIFlow contract is owned by the AIFlow gateway and its documentation:

- authenticated `GET /llm/v1/models` for the current identity;
- authenticated `POST /llm/v1/images/generations` for image generation;
- canonical models, authorization, routing, budget and retry safety remain server-owned facts.

## Decision

`aiflow-image-production` becomes the only installable image skill.

It owns:

1. a harness-neutral command-line and JSON request/result contract;
2. AIFlow environment discovery from `AIFLOW_BASE_URL` and `AIFLOW_API_KEY`;
3. live image-capable model discovery and deterministic model selection;
4. one `n=1` request per distinct asset;
5. stable error classification without leaking raw gateway bodies;
6. Base64 decoding, image verification, no-overwrite artifact commits and provenance records;
7. prompt methodology, candidate review, controlled iteration and deterministic variants;
8. model-adapter extension rules for future AIFlow image models.

All harnesses call the same executable surface. Harness-specific instructions remain thin and must not duplicate transport, model policy or artifact handling.

AIFlow remains the sole production gateway. The skill does not call providers directly and does not treat a harness-native image tool as a second production provider.

## Configuration boundary

The harness or AIFlow launcher supplies configuration:

- `AIFLOW_BASE_URL`: either the AIFlow origin or a URL ending in `/llm/v1`;
- `AIFLOW_API_KEY`: the active AIFlow or invocation credential;
- optional `AIFLOW_IMAGE_MODEL`: preferred canonical image model when more than one is available.

The skill never persists or prints credentials. It does not own login, token refresh, model grants, routing, pricing or budgets.

## Model selection

The live model list is the source of truth. A model is image-capable only when the response marks `supports_image_generation=true`.

Selection order:

1. an explicit model in the request, if live and image-capable;
2. `AIFLOW_IMAGE_MODEL`, if live and image-capable;
3. the only visible image-capable model;
4. otherwise fail with `model_selection_required` and return the safe canonical IDs.

The skill does not infer “newest” from a model name and does not carry a permanent current-model claim.

## Artifact contract

A successful generation produces:

- the exact decoded bitmap;
- verified actual format, dimensions and mode;
- SHA-256 and byte size;
- requested and returned metadata kept separately;
- a JSON provenance sidecar containing the prompt, canonical model, request ID, usage and warnings.

Writes never overwrite an existing image or sidecar. The sidecar is committed first and the image path is created last as the completion marker; callers choose a new versioned path. A completed artifact is never regenerated solely because a UI failed to display it.

## Error contract

The executable emits structured errors with:

- category;
- stable gateway code when present;
- HTTP status when present;
- `retry_safe` when explicitly returned;
- request ID when available.

Raw response bodies, Base64 payloads and credentials are never included. The executable performs no automatic retry.

## Consequences

### Positive

- One skill installation is complete and usable.
- Claude Code, Codex, Pi, Hermes and future harnesses share one executable contract.
- Model and policy facts stay in AIFlow instead of drifting into skill documentation.
- Artifact and billing safety become testable code rather than prose-only rules.
- Future AIFlow image models can be added without creating another user-facing skill.

### Negative

- `aiflow-image-production` gains a larger execution surface and must maintain tests.
- Pillow remains required for artifact verification and deterministic variants.
- More than one visible image model requires an explicit request or configured preference.

## Migration

1. Implement and verify the self-contained runtime in `aiflow-image-production`.
2. Remove all runtime dependencies and routing references to `aiflow-basic`.
3. Mark `aiflow-basic` deprecated and point users to the unified skill.
4. Retain the old repository temporarily for history and migration, then archive it after consumers have moved.
