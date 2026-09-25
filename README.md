# AIFlow Image Gen

Skill for generating and producing images through the AIFlow token service (New API gateway at `https://aiflow.archebase.ai/v1`).

## Requirements

- Python 3.10 or newer
- Pillow
- `ARCHEBASE_API_KEY` from the AIFlow token service
- optional `AIFLOW_BASE_URL` (defaults to `https://aiflow.archebase.ai/v1`)

```sh
python3 -m pip install -r requirements.txt
```

The runtime reads only `AIFLOW_BASE_URL` and `ARCHEBASE_API_KEY`. It never reads `OPENAI_*` or `ANTHROPIC_*`, and it never follows redirects.

## Check usable models

```sh
python3 scripts/aiflow_image.py models
```

The listing is advisory. `supported_endpoint_types` reflects the gateway's own record and does not prove routing: measured on 2026-09-26, `gpt-image-2.5` reports an empty list yet generates successfully. The generation call is the authoritative test, so `models` is only a hint list.

Default model is `gpt-image-2`. Set `model` in the request to use another, for example `gpt-image-2.5`.

## Generate an image

```sh
cp templates/image-request.json request.json
python3 scripts/aiflow_image.py generate --request request.json
```

The command makes one `n=1` request, verifies the returned bitmap, and writes the image plus `<image-path>.json` provenance. It refuses to overwrite an existing file unless the request sets `overwrite: true`.

Requested `size`/`quality` may be normalized by the gateway; returned values are authoritative and differences appear as warnings.

## Local checks

```sh
python3 -m unittest discover -s tests -v
```

The test suite runs against an in-process mock gateway; it needs no credential and performs no external request.
