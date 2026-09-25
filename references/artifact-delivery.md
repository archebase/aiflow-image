# Image artifact delivery and recovery

Generation is incomplete until the exact model result exists as a verified workspace file.

## Implemented AIFlow path

`scripts/aiflow_image.py generate` performs this sequence:

1. choose a stable output path before the request;
2. discover and select a live image-capable canonical model;
3. submit one `n=1` AIFlow Images request;
4. decode `data[0].b64_json` without logging it;
5. enforce output-size limits and verify the complete bitmap with Pillow;
6. compare returned format and dimensions with the decoded image;
7. commit the provenance sidecar first and create the image path last as the completion marker;
8. return absolute paths, actual metadata and SHA-256 only after both files exist. An orphan sidecar without an image is incomplete and may be removed; an image is never exposed without its sidecar during normal error handling.

Existing files are always refused. Use a new versioned output path for every generation so a partial two-file replacement cannot corrupt provenance.

## Missing UI or attachment

The workspace file and provenance sidecar are the source of truth. A harness UI not displaying the result is a delivery problem, not permission to generate another billed image. Return or inspect the recorded absolute path. If no completed Base64 result or saved artifact exists, fail honestly rather than creating a placeholder.

## Required provenance

The sidecar uses `aiflow.image-result.v1` and records backend, canonical model, prompt, requested metadata, returned metadata, actual artifact metadata, request ID, safe usage and warnings. It never contains credentials or image Base64.
