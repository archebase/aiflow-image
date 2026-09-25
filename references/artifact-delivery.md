# Image artifact delivery and recovery

The generation is incomplete until the exact model output exists as a verified workspace file.

## Standard AIFlow path

1. Before the request, choose an output directory and stable descriptive name.
2. Submit one AIFlow Images request.
3. Decode the exact `data[0].b64_json` result; never copy Base64 into chat or logs.
4. Validate PNG/JPEG/WebP signature before atomic write.
5. Avoid overwrite unless explicitly requested; create a versioned sibling name otherwise.
6. Record path, bytes, format, SHA-256, prompt, canonical model and request metadata.
7. Display or return the absolute path only after the file exists and validation passes.

## Missing UI or attachment

The AIFlow script writes the artifact directly, so UI attachments are not the source of truth. If a wrapper or future backend reports completion but the UI does not display it:

- recover from the completed result record or returned Base64/path;
- do not regenerate merely because display failed;
- do not substitute SVG, screenshots, Python drawings, test images or placeholders;
- fail honestly when the completed record contains no image data.

## Codex-hosted compatibility

If Codex built-in `image_gen` is used as an explicitly approved alternate surface, follow the same delivery invariant: mark before the call, recover the completed `image_generation_call` when UI delivery fails, validate the bitmap, and save it to the workspace without regenerating. This is a compatibility path, not an AIFlow model adapter.

## Required result record

```json
{
  "backend": "aiflow",
  "canonical_model": "gpt-image-2",
  "path": "/absolute/path/image.png",
  "format": "png",
  "bytes": 12345,
  "sha256": "...",
  "prompt": "...",
  "source_result": "b64_json",
  "retry_safe": null
}
```
