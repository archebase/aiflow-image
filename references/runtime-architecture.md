# Unified image runtime architecture

## Product boundary

There is one installable image skill and one executable contract. `aiflow-basic` is not a runtime dependency. Claude Code, Codex, Pi, Hermes and other Python-capable harnesses invoke `scripts/aiflow_image.py`; AIFlow remains the only production gateway.

## Layers

1. **Skill orchestration** — brief, prompt method, bounded candidate rounds, review, iteration and release.
2. **Harness-neutral CLI** — versioned JSON request/result contract and launcher-environment resolution.
3. **AIFlow adapter** — `/llm/v1/models` capability discovery and `/llm/v1/images/generations` execution.
4. **Artifact boundary** — Base64/container validation, full bitmap decode, no-overwrite sidecar-first commit and an image completion marker.
5. **Deterministic production** — crop, inspection, future composition and release gates.

Model policy, identity, authorization, attribution, budget, route choice and provider credentials are not duplicated in the skill. They are server-owned AIFlow facts.

## Current implemented capability

- authenticated live model discovery;
- generation through AIFlow Images;
- one image per request;
- PNG, JPEG and WebP artifact verification;
- requested and actual metadata separation;
- structured safe errors with no automatic retry;
- cross-harness launcher discovery for AIFlow-configured environments.

The runtime does not currently implement Images edits, reference-image upload, streaming partial images or URL-result download. The skill must report those operations as unsupported rather than simulate them.

## Future model/provider adaptation

A future AIFlow image model does not require a new user-facing skill. If it uses the existing Images request/result contract, live capability discovery is sufficient. If it introduces a different protocol, add an internal adapter behind the same `aiflow.image-request.v1` result and prove:

- canonical model discovery;
- supported input fields and limits;
- output transport and artifact persistence;
- retry/billing safety semantics;
- positive generation evidence;
- fail-closed negative controls for unsupported operations.

Never infer compatibility solely from an OpenAI-like endpoint shape, and never expose provider account or physical route details as model truth.
