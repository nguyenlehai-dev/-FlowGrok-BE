# FlowGrok Gateway Phase Plan

## Current Runtime

FlowGrok currently exposes an API gateway surface to clients, but the default provider runtime is browser automation:

```text
client API -> FlowGrok job -> VPS worker -> Playwright browser -> grok.com
```

This remains unchanged.

## Phase 1: Gateway Mode Scaffold

Phase 1 adds an opt-in provider mode without changing existing jobs:

```json
{
  "provider_mode": "gateway"
}
```

When this flag is present in `request_payload`, the worker uses `GrokGatewayProvider` instead of the browser automation provider.

Default jobs without this flag still use the existing browser automation flow.

## Required Runtime Config

Gateway mode is disabled until both environment variables are configured:

```text
GROK_GATEWAY_ENDPOINT=https://provider.example.com/generate
GROK_GATEWAY_API_KEY=...
```

If either value is missing, the job fails with:

```text
GATEWAY_NOT_CONFIGURED
```

This is intentional so a client can distinguish "gateway not configured" from Cloudflare/browser challenges.

## Expected Gateway Contract

FlowGrok sends:

```json
{
  "job_type": "generate_image",
  "prompt": "prompt text",
  "request_payload": {}
}
```

The configured gateway can return one of:

```json
{
  "result_url": "https://..."
}
```

```json
{
  "result_base64": "...",
  "mime_type": "image/png"
}
```

```json
{
  "file_path": "/absolute/path/to/result.png",
  "mime_type": "image/png"
}
```

It may also return binary content directly with an image or video `Content-Type`.

## What This Solves

Gateway mode does not use:

- Playwright
- browser cookies
- persistent browser session
- grok.com web UI

That means gateway mode does not hit the browser-level Cloudflare `Just a moment...` challenge.

## What This Does Not Solve Yet

This scaffold does not invent an official Grok API. It needs a real provider endpoint or official API credential to call.

Until that exists, browser automation remains the default working mode.

## Next Phases

1. Add per-profile provider mode selection in UI.
2. Add secure admin config for `GROK_GATEWAY_ENDPOINT` and `GROK_GATEWAY_API_KEY`.
3. Add provider-specific response normalization once the real gateway contract is known.
4. Add tests with a mocked gateway endpoint.
5. Add docs to `/api-docs` once the final gateway contract is confirmed.
