# Codex image backend and delivery

Use this reference only when the selected backend is Codex's built-in image generation. AIFlow remains preferred when organizational routing, governed billing or AIFlow provenance is required.

## Required Codex skills

- Load Codex system `imagegen` for prompting, generation/edit semantics and save-path rules.
- Load `codex-image-delivery` when the desktop UI does not display or persist a completed built-in `image_gen` result.

Do not copy these Codex skills into this repository. They are upstream runtime skills; this skill composes them.

## Backend selection

- Explicit AIFlow request or governed organizational work: use `aiflow-basic` and AIFlow Images.
- Explicit Codex/native image request, or user-approved native backend: use Codex `imagegen`.
- Never silently switch after a failure. Record backend, model and reason.

## Codex generation workflow

1. Use built-in `image_gen` by default; do not use API/CLI fallback solely for path control.
2. Before the call, when reliable workspace delivery is required, create the marker required by `codex-image-delivery`.
3. Run exactly one built-in call per requested asset or variant.
4. Inspect the completed output for brief fit and defects.
5. Move/copy selected project assets from Codex's generated-image location into the workspace.
6. If the UI attachment is missing, extract the exact completed `image_generation_call` result with `codex-image-delivery`; do not regenerate and do not create a substitute.
7. Validate the recovered file signature and absolute path before use.

## Prompt rules inherited from Codex imagegen

- Distinguish generation from edit intent.
- Label every reference image role.
- Preserve edit invariants on every iteration.
- Separate distinct assets into distinct calls; do not use one `n` value for unrelated prompts.
- Generate bitmap assets, not SVG/HTML placeholders, when the request is for a raster image.
- Report the final prompt and saved project path.

## ArcheBase overlay boundary

Codex generation creates the background/master image without official Logo or final text. Place official ArcheBase assets after generation through `archebase-vi-guide` and run the same release gates as an AIFlow-generated master.
