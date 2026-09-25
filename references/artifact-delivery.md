# Artifact delivery and recovery

Generation is incomplete until the exact result exists as a verified file.

## What the runtime does

`scripts/aiflow_image.py generate`:

1. resolves and pre-checks the output path before any gateway call;
2. lists image-capable models, then selects one;
3. submits exactly one `n=1` request to `POST /v1/images/generations`;
4. decodes `data[0].b64_json` without logging it;
5. validates the container, fully loads the bitmap with Pillow, and checks that reported `size`/`output_format` match;
6. writes the image and `<image-path>.json` provenance;
7. returns absolute paths, actual metadata, SHA-256, `request_id`, `generation_id`, usage and warnings.

Existing output is refused unless the request sets `overwrite: true`. Prefer a new versioned path so provenance and pixels never disagree.

## Delivery is the file, not the UI

The saved file plus provenance is the source of truth. A harness that fails to display the image is a display problem — not a reason to generate (and pay for) another one. If no artifact and no completed result exist, report the failure instead of creating a placeholder.

## Provenance contents

`aiflow.image-result.v1`: gateway, canonical model, prompt, requested vs returned parameters, actual artifact metadata (format, dimensions, mode, bytes, SHA-256), `request_id`, `generation_id`, usage and warnings. It never contains the credential or the Base64 payload.
