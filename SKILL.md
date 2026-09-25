---
name: aiflow-image-production
description: End-to-end complex image production through AIFlow. Use for multi-round image direction, multiple candidates, reference-image consistency, campaign or social variants, compositing, crop families, brand-sensitive graphics, human selection and release QA. Use aiflow-basic for live model discovery and simple image calls; also load archebase-vi-guide whenever the artifact is ArcheBase-branded.
license: Proprietary. For ArcheBase organization use only.
metadata:
  version: "0.1.0"
  dependencies: "aiflow-basic; archebase-vi-guide for branded work"
compatibility: "Requires Python 3, Pillow, aiflow-basic, and authorized AIFlow image-generation access."
---

# AIFlow Image Production

A production workflow, not a larger prompt. It turns a brief into traceable candidates, controlled iterations, deterministic variants and a release decision. AIFlow remains the model gateway; this skill owns art direction and delivery.

## Required references

1. Load `references/brief-and-routing.md` before selecting a backend or model.
2. Load `references/prompt-compiler.md` before the first generation.
3. Load `references/iteration-and-review.md` before selecting or revising candidates.
4. Load `references/consistency.md` whenever subjects, products or styles must remain stable.
5. Load `references/brand-production.md` plus `archebase-vi-guide` for ArcheBase-branded output.
6. Fill `templates/brief.md` and `templates/generation-record.md`; finish with `templates/release-report.md`.

## Workflow

1. Resolve the claim, audience, placement, aspect ratios, factual boundary, rights and success criteria.
2. Use `aiflow-basic` to discover current models and authorize the chosen Images route.
3. Compile a prompt that separates immutable constraints, composition, subject, style, exclusions and open creative latitude.
4. Generate a bounded candidate set. Record model, prompt, parameters, cost-risk state and output hashes.
5. Review candidates for brief fit, visual defects, accidental text/logos, factual implication, rights and crop resilience.
6. Iterate only with a stated change hypothesis. Do not issue vague "make it better" rounds.
7. Produce deterministic aspect-ratio variants and post-production through scripts; do not ask the model to generate final brand marks or final typography.
8. Run channel and brand release gates. Return selected files, provenance, rejected alternatives, unresolved blockers and one verdict.

## Backend policy

Use AIFlow when the user requests organizational routing, governed billing, canonical model selection or AIFlow provenance. Native `image_gen` may be used only when the user allows that backend or AIFlow is not required. Never silently switch backends; record backend, model and reason.

## Hard boundaries

- Never generate or approximate an official Logo. Add approved assets after generation.
- Never rely on generated text for final copy, labels or metrics.
- Never depict a specific customer site, capability or real person without evidence and rights.
- Never publish an image without source, prompt/model record, rights status and human acceptance.
- Never auto-retry a charge-unknown AIFlow error; respect `retry_safe`.

## Output contract

Return the selected master, requested variants, contact sheet when useful, generation/provenance record, release report and exact unresolved blockers. Separate generated pixels from deterministic overlays and official assets.
