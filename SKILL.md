---
name: aiflow-image-production
description: Generate and produce raster images through the configured AIFlow gateway. Use for every AIFlow image request, including one-shot generation, candidate sets, controlled iteration, consistent visual families, campaign masters, deterministic crops, artifact recovery, brand-sensitive graphics and release QA. This skill is self-contained and works across AIFlow-configured Claude Code, Codex, Pi and other Python-capable harnesses; do not require aiflow-basic or call a provider directly.
license: Proprietary. For ArcheBase organization use only.
metadata:
  version: "2.0.0"
  runtime_contract: "aiflow.image-request.v1"
compatibility: "Requires Python 3.10+, Pillow 12.0.0, and an AIFlow-configured harness environment. ArcheBase-branded work also requires archebase-vi-guide."
---

# AIFlow Image Production

Use one self-contained AIFlow workflow for both simple generation and production work. Model discovery, authorization, routing, budget and canonical model facts remain owned by AIFlow; this skill compiles the request, invokes the gateway, verifies the artifact and manages review and delivery.

## Required execution path

1. Read `references/runtime-contract.md` before the first gateway call in a session.
2. Read `references/generation-methodology.md` and `references/prompt-compiler.md` before compiling the first prompt.
3. Read `references/artifact-delivery.md` before choosing an output path.
4. When adding a future image protocol or model adapter, first read `references/runtime-architecture.md`, `references/verified-adapters.md` and `templates/model-adapter.md`; keep unproven capabilities unsupported.
5. Write a request using `templates/image-request.json`, then run:

   ```bash
   python3 scripts/aiflow_image.py generate --request request.json
   ```

6. Treat the command's JSON result and saved provenance sidecar as the execution record. Never reconstruct success from chat text or a missing UI attachment.
7. Read `references/iteration-and-review.md` before selecting or revising candidates. For repeated subjects or a visual family, also read `references/consistency.md`.
8. For ArcheBase-branded output, load `archebase-vi-guide` and read `references/brand-production.md` before composition or release.

## Workflow

1. Resolve the deliverable, audience, placement, dimensions, factual boundary, rights and success criteria. Use `templates/brief.md` for production work; do not force a full brief for a straightforward one-image request.
2. Compile a concrete prompt. Keep official marks, final typography and exact data overlays out of generated pixels.
3. Generate one distinct asset per command. A candidate set is a bounded series of separate requests, normally 2–4, with unique output paths.
4. Let the runtime discover live image-capable canonical models. Specify `model` only when the user or production plan requires one; never infer a newest model from its name.
5. Inspect every saved artifact for brief fit, geometry, accidental text or marks, factual implications, rights and crop resilience.
6. Iterate with one stated hypothesis at a time and restate accepted invariants.
7. Create deterministic crops with `scripts/make_variants.py` and inspect deliverables with `scripts/inspect_image.py`. Add official assets and final text only in deterministic post-production.
8. Run the pre-delivery gate: verify the artifact and sidecar exist, hashes and dimensions match, requested variants open correctly, provenance and rights are recorded, brand/channel gates passed, and a human selected the release candidate.

## Runtime rules

- Use only the configured AIFlow gateway. Do not call OpenAI or another provider directly and do not use a harness-native image generator as a silent fallback.
- The runtime uses `AIFLOW_*` for generic/Pi launches and accepts `OPENAI_*` or `ANTHROPIC_*` only when `AIFLOW_TOOL` identifies an AIFlow Codex or Claude launch. It refuses provider `/v1` paths and never follows redirects; the launcher/operator owns the trusted AIFlow hostname.
- The live `/llm/v1/models` response is the model source of truth. If several image-capable models are visible, select one explicitly or configure `AIFLOW_IMAGE_MODEL`.
- Never put credentials in command arguments, files, prompts, logs or chat.
- Never retry automatically. Retry only after the returned structured error explicitly reports `retry_safe: true` and the user or workflow approves the additional cost.
- A completed artifact is not regenerated merely because a harness UI failed to display it.

## Hard boundaries

- Never generate or approximate an official Logo; composite approved assets after generation.
- Never rely on generated text for final copy, labels, metrics or precise diagrams.
- Never depict a specific customer deployment, capability or real person without evidence and rights.
- Never publish without provenance, rights status, visual review and human acceptance.
- Do not claim edit, reference-image, transparency, streaming or consistency capability unless the live AIFlow request actually supports and proves it.

## Output contract

Return the selected image path, provenance sidecar path, canonical model, actual format and dimensions, SHA-256, warnings and unresolved blockers. For production work, also return the requested variants and a release verdict: `ready`, `revise` or `blocked`.
