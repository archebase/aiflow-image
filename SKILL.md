---
name: aiflow-image-gen
description: Generate and produce raster images through the AIFlow token service (New API gateway). Use for any AIFlow image request — one-shot generation, candidate sets, controlled iteration, consistent visual families, campaign masters, deterministic crops, artifact recovery and brand-sensitive graphics — and whenever an image must be written to disk with verifiable provenance. Works in any Python-capable harness whose environment carries AIFLOW_BASE_URL and ARCHEBASE_API_KEY; never call a model provider directly.
license: Proprietary. For ArcheBase organization use only.
metadata:
  version: "3.0.0"
  runtime_contract: "aiflow.image-request.v1"
compatibility: "Requires Python 3.10+, Pillow 12.0.0, AIFLOW_BASE_URL and ARCHEBASE_API_KEY. ArcheBase-branded work also requires archebase-vi-guide."
---

# AIFlow Image Generation

Generate images through the AIFlow token service and deliver verified files. The gateway owns models, authorization, routing, budget and billing; this skill compiles the request, calls the gateway, verifies the artifact and manages review and delivery.

## Required execution path

1. Read `references/runtime-contract.md` before the first call in a session — it records the verified gateway contract.
2. For production work, read `references/prompt-compiler.md` and `references/generation-methodology.md` before compiling prompts.
3. Read `references/artifact-delivery.md` before choosing an output path.
4. Write a request from `templates/image-request.json`, then run:

   ```bash
   python3 scripts/aiflow_image.py models
   python3 scripts/aiflow_image.py generate --request request.json
   ```

5. Treat the command's JSON result and the provenance sidecar as the record. Do not reconstruct success from chat text.
6. Read `references/iteration-and-review.md` before selecting or revising candidates; read `references/consistency.md` when a subject must stay stable across images.
7. For ArcheBase-branded output, load `archebase-vi-guide` and read `references/brand-production.md`.

## Workflow

1. Resolve deliverable, audience, placement, dimensions and rights. Skip the full brief for a simple one-image request; use `templates/brief.md` for production work.
2. Compile a concrete prompt. Keep official logos, final typography and exact figures out of generated pixels.
3. Generate one asset per command. A candidate set is a bounded series of separate requests with unique output paths.
4. Treat `/v1/models` as advisory. Its `supported_endpoint_types` field does not prove a route works: `gpt-image-2.5` declares an empty list yet generates successfully on the live gateway. The generation call is the only authoritative test.
5. Inspect every saved artifact against the brief.
6. Iterate with one stated hypothesis at a time.
7. Derive crops with `scripts/make_variants.py`, inspect files with `scripts/inspect_image.py`, and add official assets and typography afterwards.
8. Before delivery confirm: image and sidecar exist, hashes and dimensions match, variants open, provenance is recorded, and a human accepted the release candidate.

## Runtime rules

- Configuration is `AIFLOW_BASE_URL` (which defaults to `https://aiflow.archebase.ai/v1`) and `ARCHEBASE_API_KEY`. Never put the credential in prompts, files, command arguments or chat output.
- Model availability is decided by the generation call, not by `supported_endpoint_types`. Default model is `gpt-image-2`; set `model` in the request to use another.
- The gateway may normalize `size` and `quality`. Returned values are authoritative; a difference from the request is a warning, not a failure.
- Never retry automatically. Retry only when the structured error reports `retry_safe: true` and a human accepts the extra cost.
- A completed artifact is not regenerated because a harness UI failed to display it.
- Do not claim edit, reference-image, streaming or transparency support unless a real gateway request proves it.

## Hard boundaries

- Never generate or approximate an official logo; composite approved assets after generation.
- Never rely on generated text for final copy, labels, metrics or diagrams.
- Never depict a specific customer site, capability or real person without evidence and rights.
- Never publish without provenance, rights status, visual review and human acceptance.

## Output contract

Return the image path, provenance path, canonical model, actual format and dimensions, SHA-256, warnings and unresolved blockers. For production work also return the requested variants and a verdict: `ready`, `revise` or `blocked`.
