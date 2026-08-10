# Media Engine (services/media_engine)

The media engine is bark's in-repo graphics/render service — the thing
behind the `profiles` plugin's `/bark profile` cards, and available to any
module that wants rendered images (profile cards, posters, GIFs, ...).

It runs as a **separate process per instance** (`bark-media-engine.service`
for prod on :8094, `bark-media-engine-dev.service` for dev on :8095) so
CPU-heavy Pillow renders never block the bot's event loop. The code lives in
this repo: `services/media_engine/` (package) + `tests/test_media_engine/`
(tests) + bundled assets (fonts/themes).

## API (localhost only, Bearer token)

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness + version + configured AI model |
| `POST /v1/render` | submit a render job `{kind, guild_id, user_id, theme, art_mode, payload, output, cache_ttl}` |
| `GET /v1/jobs/{id}` | job status → `{status, file, size, error, cost_usd}` |
| `POST /v1/payload` | engine-collected data blocks (reputation/activity/badges/favorites) |
| `GET /v1/theme` | available theme packs |

Renders are cached by content hash (payload-stable) with a per-request TTL;
identical requests return the same file. Output files land in
`<BARK_MEDIA_DATA_DIR>/media-cache/<kind>/` — clients read the path directly
(same host).

## Using it from a module or plugin

```python
from services.media_engine.client import MediaEngineClient

client = MediaEngineClient()          # env: BARK_MEDIA_ENGINE_URL / BARK_MEDIA_ENGINE_TOKEN
data = await client.collect_payload("profile", guild_id, user_id)
path = await client.render("profile", guild_id, user_id, payload=data)
# path → local PNG; post it, attach it, whatever you need
```

The client raises `MediaEngineUnavailable` (engine down) and
`MediaEngineError` (job failed) — catch them and fall back gracefully.

## Adding a render kind for your module

1. Create `services/media_engine/renderers/<name>.py` with a
   `@register("<kind>")` function `fn(payload, theme, **kwargs) -> PIL.Image`
   (see `renderers/profile.py` for the pattern; it is imported eagerly in
   `renderers/__init__.py`).
2. Collect what you need in `collect.py` (read-only SQL against the
   instance DB) and expose it via `collect_payload` if the plugin/module
   side should merge it with live Discord facts.
3. Test in `tests/test_media_engine/` (renderer smoke + API lifecycle
   patterns in `test_profile_render.py` / `test_render_api.py`).

## Data sources (real-data only)

The card renders nothing bark cannot actually obtain:

- `user.*`, `roles` → Discord API (live member/user, supplied by the caller)
- `reputation.*` → `reputation_profiles` + `reputation_tiers` (incl.
  next-tier progress; degenerate curves with equal thresholds hide the label)
- `badges` → `reputation_awards` ⋈ `reputation_rewards`
- `activity` bars → `reputation_events` (7-day daily + 28-day weekly buckets)
- `favorites` → `reputation_events.channel_id` counts (+ live channel names)

## Running it

```bash
# per instance, e.g. dev:
sudo cp docs/systemd/bark-media-engine.service /etc/systemd/system/bark-media-engine-dev.service
# edit: WorkingDirectory + EnvironmentFile + port (dev = 8095)
sudo systemctl daemon-reload && sudo systemctl enable --now bark-media-engine-dev.service
```

Env (per instance `.env`):
- `BARK_MEDIA_ENGINE_TOKEN` — shared with the plugin/module clients
- `BARK_MEDIA_ENGINE_URL` — what clients should call (dev: :8095)
- `BARK_MEDIA_DB_PATH` — instance DB for engine-side collection
- `BARK_MEDIA_DATA_DIR` — render cache + CDN avatar cache
- `BARK_MEDIA_AI_MODEL` / `BARK_MEDIA_OPENAI_API_KEY` — AI art direction (Phase 3)
