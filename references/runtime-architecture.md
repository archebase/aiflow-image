# Unified image runtime architecture

## Capability contract

The skill owns one model-agnostic production contract:

- discover authorized image-generation capabilities;
- generate a new raster image;
- edit an existing raster image when supported;
- accept labeled reference images when supported;
- create multiple assets or variants as separate jobs;
- preserve delivery artifacts and provenance;
- report unsupported capability instead of silently degrading.

## Current implementation

AIFlow currently exposes one production image family:

| Capability | Current implementation |
|---|---|
| Provider family | OpenAI GPT Image through AIFlow |
| Canonical model | `gpt-image-2` |
| Protocol | `POST /llm/v1/images/generations` |
| Generation | Supported |
| Image edit | Not currently exposed by AIFlow |
| Reference-image generation | Not currently exposed by AIFlow generations contract |
| Native transparent output | Not supported by current `gpt-image-2` route |
| Images per request | `n=1` |
| Output | `b64_json` decoded to PNG/JPEG/WebP |
| Streaming | Supported with partial images when enabled |

Do not present Codex built-in generation as a second AIFlow provider. Codex's image workflow is absorbed as production methodology and delivery behavior; actual AIFlow execution currently remains GPT-only.

## Future provider slots

Future models must implement the same capability record before use:

- canonical model ID;
- provider family;
- protocol and endpoint;
- generate/edit/reference/stream/transparent capability booleans;
- accepted sizes, ratios, formats and batch limits;
- output transport and artifact persistence;
- retry/billing safety contract;
- provenance fields;
- negative controls proving unsupported operations fail closed.

Until an adapter exists and is verified, mark the provider `unsupported`; leave the implementation slot empty rather than guessing compatibility.
