# AIFlow Image Skill

One self-contained image-generation and production skill for every AIFlow-configured harness. It replaces the former `aiflow-basic` dependency and supports both one-shot generation and multi-round production workflows.

## Requirements

- Python 3.10 or newer
- Pillow
- AIFlow service configuration: `AIFLOW_BASE_URL` and `AIFLOW_API_KEY`

```sh
python3 -m pip install -r requirements.txt
```

The runtime reads exactly two AIFlow service variables:

```text
AIFLOW_BASE_URL
AIFLOW_API_KEY
```

It never consumes provider-named variables such as `OPENAI_*` or `ANTHROPIC_*`. Follow the AIFlow service documentation (for example its `llms.txt`) for the deployment values.

The runtime accepts only an AIFlow origin or `/llm[/v1]` URL and refuses provider-direct URLs.

## Generate an image

Create `request.json` from `templates/image-request.json`, then run:

```sh
python3 scripts/aiflow_image.py generate --request request.json
```

The command discovers live image-capable models, makes one `n=1` request, verifies the decoded bitmap and commits a provenance sidecar followed by the image completion marker:

- the image;
- `<image-extension>.json`, a provenance sidecar.

List safe model capabilities without exposing provider routes or credentials:

```sh
python3 scripts/aiflow_image.py models
```

## Model selection

The runtime selects in this order:

1. `model` in the request;
2. `AIFLOW_IMAGE_MODEL`;
3. the only live image-capable model.

If several models are visible and no preference is provided, it fails with `model_selection_required` instead of guessing which model is newest.

## Validation

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py tests/*.py
python3 -m json.tool evals/evals.json >/dev/null
```

See `docs/adr-0001-unified-image-skill.md` for the consolidation decision and runtime ownership boundary.
