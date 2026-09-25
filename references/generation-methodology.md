# Image generation methodology

## Decide intent

- **Generate:** create a new raster image through the implemented AIFlow Images adapter.
- **Edit:** preserve an existing image while changing named regions or properties. The current runtime has no edit transport; report unsupported instead of simulating an edit with generation.

## Execution strategy

- One distinct asset or variant is one generation command and one unique output path.
- Produce bounded candidate rounds, normally 2–4 assets.
- Classify the request before prompting: photorealistic, product mockup, UI mockup, infographic/diagram, scientific/educational, marketing, illustration/story, stylized concept or historical scene.
- Use live model capability discovery. Do not embed a current-model list or infer which ID is newest.

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
Text (verbatim, only when unavoidable):
Constraints:
Avoid:
```

Structure content as scene → subject → details → constraints → output intent. Normalize a specific prompt rather than expanding it gratuitously. For a generic prompt, add only composition, intended-use and practical layout details that materially help.

## Constraints and references

- Label supplied images by index and role, but do not send them unless an implemented runtime adapter supports reference inputs.
- Never claim reference fidelity or edit invariants from prompt-only generation.
- For page copy, request usable negative space; add exact typography deterministically after generation.
- Requested transparency is not proof of model support. Let AIFlow validate the selected model and report the structured rejection honestly.

## Iteration

Inspect subject, style, composition, text artifacts and constraints. Iterate with one targeted hypothesis and re-state accepted invariants. Never repeat an identical request after cancellation, timeout, partial delivery or another charge-unknown failure unless billing state is understood and the server explicitly marks retry safe.
