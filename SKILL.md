---
name: aiflow-image-production
description: Unified end-to-end image generation and production through AIFlow. Use for simple or complex raster generation, candidate sets, controlled iteration, future image-model routing, reference consistency when supported, artifact recovery, crop families, compositing, brand-sensitive graphics and release QA. The skill absorbs Codex imagegen prompting/delivery methodology, while the current AIFlow implementation supports only GPT Image through gpt-image-2; unsupported future providers stay explicit and empty until verified.
license: Proprietary. For ArcheBase organization use only.
metadata:
  version: "1.0.0"
  dependencies: "aiflow-basic for live gateway calls; archebase-vi-guide for branded work"
compatibility: "Requires Python 3, Pillow, aiflow-basic, and authorized AIFlow image-generation access. Current production adapter: AIFlow gpt-image-2 generations."
---

# AIFlow Image Production

The unified image-production skill for AIFlow. It owns the complete workflow from prompt shaping through exact artifact delivery and future provider adaptation. AIFlow remains the governed gateway; today its verified implementation is GPT Image 2 generations only.

## Required references

1. Load `references/runtime-architecture.md` before claiming a model capability.
2. Load `references/brief-and-routing.md` before selecting a production path.
3. Load `references/generation-methodology.md` and `references/prompt-compiler.md` before the first generation.
4. Load `references/artifact-delivery.md` before generating whenever a workspace file is required.
5. Load `references/iteration-and-review.md` before selecting or revising candidates.
6. Load `references/consistency.md` whenever subjects, products or styles must remain stable.
7. Load `references/brand-production.md` plus `archebase-vi-guide` for ArcheBase-branded output.
8. Fill `templates/brief.md` and `templates/generation-record.md`; use `templates/model-adapter.md` for future models and finish with `templates/release-report.md`.

## Workflow

1. Resolve the claim, audience, placement, aspect ratios, factual boundary, rights and success criteria.
2. Use `aiflow-basic` to discover the live canonical model list and verify an authorized Images route.
3. Read the selected model's verified adapter. Current production path is `gpt-image-2` generations; leave unsupported capabilities blocked.
4. Compile the prompt using the absorbed imagegen methodology: intent, use-case class, scene, subject, composition, style, constraints and exclusions.
5. Generate one distinct asset per request. For candidate sets, issue bounded separate `n=1` requests and record every output.
6. Save and validate the exact model artifact before review. A missing UI attachment is a delivery problem, not permission to regenerate.
7. Review candidates for brief fit, visual defects, accidental text/logos, factual implication, rights and crop resilience.
8. Iterate only with a stated single-change hypothesis and re-state invariants.
9. Produce deterministic variants and overlays through scripts; do not ask the model to generate final brand marks or final typography.
10. Run channel and brand release gates. Return selected files, provenance, rejected alternatives, unresolved blockers and one verdict.

## Runtime policy

AIFlow is the production gateway. The current verified adapter is GPT Image 2 via `/llm/v1/images/generations`. Codex imagegen methodology is absorbed into this skill; Codex built-in execution is only an explicitly approved compatibility surface, not a second AIFlow provider. Future models remain `unsupported` until an adapter is filled, tested and approved.

## Hard boundaries

- Never generate or approximate an official Logo. Add approved assets after generation.
- Never rely on generated text for final copy, labels or metrics.
- Never depict a specific customer site, capability or real person without evidence and rights.
- Never publish an image without source, prompt/model record, rights status and human acceptance.
- Never auto-retry a charge-unknown AIFlow error; respect `retry_safe`.

## Output contract

Return the selected master, requested variants, contact sheet when useful, generation/provenance record, release report and exact unresolved blockers. Separate generated pixels from deterministic overlays and official assets.
