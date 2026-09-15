# Milestone A — trustworthy core

Scope: local `improvement/milestone-a` branch from `ca262aff25f3716d38d94f38be98b85dc13cf9f9`. No stable promotion, live configuration edits, score/tier migrations, or Discord test messages authorized.

## Immutable baseline

- pytest: 926 passed, 1 failed; schedule API test raised `KeyError: data`.
- Ruff: 19 lint violations; 129 files would be reformatted.
- mypy: 50 errors in 22 files (129 source files checked).
- Bandit CI command: four medium findings, zero high. Findings require individual review, not blanket suppression.
- pip-audit: six reported rows for aiohttp 3.14.1 (duplicate advisory IDs present).
- Frontend: `npm ci` and `npm run check` passed; committed assets reproduce.
- Existing untracked `.hermes-tmp/` and `docs/audits/2026-08-12-24h-audit.md` are unrelated and excluded.
- No visual changes in A; screenshot/design work belongs to B.

## Acceptance criteria

- Attachment cleanup handles expired attachment records repeatedly.
- Reputation partial updates preserve omitted role links; numeric inputs validated; ignored-role policy enforced; self-reaction awards rejected without rewriting historical data.
- Dashboard staff-role changes refresh authorization; realtime access is revoked promptly and reconnects are checked.
- Plugin catalog I/O does not block the event loop.
- Announcement scheduling API regression is diagnosed and green.
- Dev CI triggers and generated-asset checks enabled.
- Full pytest, lint, formatting, mypy, Bandit and dependency auditing pass; frontend builds reproducibly.
- Independent review and parent verification; stable remains untouched.

## Confirmed diagnosis during implementation

The schedule API correctly returned HTTP 400: `Scheduled time must be in the future`. Its test hardcoded 2026-09-01, which expired. The fixture now uses tomorrow in UTC and asserts response status before consuming data. The production endpoint was not weakened. Schedule API and scheduler tests: 10 passed.

## Change separation

Behavioral fixes and mechanical lint/format cleanup must remain independently reviewable. Do not mix unrelated untracked work into this milestone. No commit or push is implied by local implementation.
