# Image generation methodology

This is the in-repository production methodology absorbed from Codex imagegen principles and adapted to AIFlow's current GPT Image contract.

## Decide intent

- **Generate:** create a new image. Supplied images may be composition, mood or subject references only when the runtime supports them.
- **Edit:** preserve an existing image while changing named regions or properties. AIFlow currently does not expose Images edits; report unsupported instead of simulating an edit with generation.

## Execution strategy

- One distinct asset or variant is one generation job.
- Do not use a count parameter to stand in for unrelated prompts.
- Produce bounded candidate rounds, normally 2–4 images, as separate `n=1` AIFlow requests.
- Classify the request before prompting: photorealistic-natural, product-mockup, ui-mockup, infographic-diagram, scientific-educational, ads-marketing, productivity-visual, illustration-story, stylized-concept or historical-scene.

## Prompt structure

Use short labeled fields as needed:

```text
Use case:
Asset type:
Primary request:
Scene/backdrop:
Subject:
Style/medium:
Composition/framing:
Lighting/mood:
Color palette:
Materials/textures:
Text (verbatim):
Constraints:
Avoid:
```

Structure content as scene → subject → details → constraints → output intent. If the user prompt is specific, normalize rather than expanding it. If generic, add only composition, intended-use and practical layout details that materially improve the result.

## Constraints and references

- Label every supplied image by index and role.
- Do not claim reference-image fidelity when the active runtime has no reference-image input.
- For edits, repeat `change only X; keep Y unchanged`; currently block edit execution until AIFlow exposes an edit-capable adapter.
- For assets needing page copy, request usable negative space without inventing arbitrary left/right placement.

## Text and transparency

- Generated final text is discouraged for production. Prefer deterministic typography after generation.
- If exact generated text is unavoidable, quote it verbatim and require no extra characters, but keep human verification mandatory.
- Current AIFlow `gpt-image-2` supports `background=auto|opaque`, not native transparent output. Do not silently switch providers or pretend transparency is supported.

## Iteration

Inspect subject, style, composition, text accuracy and constraints. Iterate with one targeted change at a time and re-state invariants. Do not re-run an identical charge-unknown request; obey AIFlow's retry-safe contract.
