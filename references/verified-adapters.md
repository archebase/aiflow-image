# Model adapter policy

This file deliberately contains no permanent list of current model IDs. Live AIFlow model discovery is the source of truth for every invocation.

## Existing adapter

The implemented adapter is the AIFlow Images gateway:

- discovery: authenticated `GET /llm/v1/models`;
- capability flag: `supports_image_generation=true`;
- generation: authenticated `POST /llm/v1/images/generations`;
- output: exactly one `data[0].b64_json` artifact;
- retry: none automatically; honor only an explicit server `retry_safe` result;
- provenance: canonical model, request/returned metadata, request ID, usage and verified artifact hash.

## Adding another protocol

Use `templates/model-adapter.md`. Keep the adapter `unsupported` until tests prove every supported claim and negative controls prove unsupported operations fail closed. A recorded smoke result is evidence for that test run, not a timeless claim that the model remains available to every identity.
