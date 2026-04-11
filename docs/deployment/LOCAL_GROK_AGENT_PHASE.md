# FlowGrok Local Agent Phase

## Goal

This phase keeps the current server flow unchanged and adds a separate local tool flow:

```text
client API -> user machine local agent -> local Playwright browser -> grok.com
```

The user runs the tool on their own machine, logs in to Grok in the local browser profile, and can expose the local API through a tunnel or reverse proxy if they choose.

## What Changed

- Added a standalone FastAPI app at `app.local_agent.main`.
- Added `scripts/run-local-agent.sh` for local startup.
- Reused the existing Grok Playwright provider and persistent browser profile storage.
- Added optional API key protection with `FLOWGROK_LOCAL_API_KEY`.
- Kept the existing VPS API, worker, PostgreSQL, frontend, and production flow untouched.

## Run Locally

From the backend repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
HOST=127.0.0.1 PORT=8765 ./scripts/run-local-agent.sh
```

For a published API, set an API key first:

```bash
export FLOWGROK_LOCAL_API_KEY="change-this-key"
HOST=0.0.0.0 PORT=8765 ./scripts/run-local-agent.sh
```

Do not expose the local agent publicly without an API key and a trusted network path.

## Session Flow

The default local profile is stored under:

```text
storage/profiles/local-grok/browser
```

Start with a headed browser so the user can complete normal Grok login:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/session/check \
  -H 'Content-Type: application/json' \
  -d '{"headless": false}'
```

After login succeeds, later jobs reuse the same persistent browser profile.

## API Examples

Health:

```bash
curl http://127.0.0.1:8765/health
```

Create an image job:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: change-this-key' \
  -d '{
    "job_type": "generate_image",
    "prompt": "a product photo on a clean table",
    "headless": false
  }'
```

Create a video job:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: change-this-key' \
  -d '{
    "job_type": "generate_video",
    "prompt": "a slow cinematic camera move",
    "request_payload": {
      "video_resolution": "480p",
      "video_duration": "6s"
    },
    "headless": false
  }'
```

List jobs:

```bash
curl -H 'X-API-Key: change-this-key' http://127.0.0.1:8765/api/v1/jobs
```

Get job artifacts:

```bash
curl -H 'X-API-Key: change-this-key' \
  http://127.0.0.1:8765/api/v1/jobs/{job_id}/artifacts
```

## Current Limits

- Jobs are kept in memory, while artifact files are persisted under `storage/jobs`.
- This phase is not packaged as an exe yet.
- The local agent does not bypass Grok or Cloudflare challenges. It uses the user's own local browser session.
- Concurrent jobs should be kept conservative per profile because one persistent browser profile should not be driven by many jobs at the same time.

## Next Phase

1. Add persisted local job state.
2. Add single-profile queue locking to prevent concurrent browser profile conflicts.
3. Package the agent as an executable for customer machines.
4. Add a small desktop or tray UI for login/session status.
5. Add tunnel setup docs once the customer's preferred tunnel is confirmed.
