# Release Process — merging `dev` into stable

This document is the single source of truth for promoting the Bark `dev`
branch to the stable line and deploying it to the running instances.
Follow it top to bottom for every release. If a step fails, stop and
resolve before continuing (see Rollback).

## Topology

| Thing        | Location / value                                             |
|--------------|--------------------------------------------------------------|
| Stable branch | `master` (local + Forgejo `origin`) — GitHub mirror: `main` |
| Dev branch    | `dev` (local + Forgejo `origin`) — GitHub mirror: `dev`     |
| Source of truth | Forgejo `http://10.0.0.137:3000/cody/bark.git`            |
| GitHub mirror | `https://github.com/warmbo/bark.git` (owner-synced, read-only from these boxes) |
| Dev instance  | `cody@10.0.0.227:~/Projects/bark-dev`, branch `dev`, port `8091`, unit `bark-dev.service` |
| Prod instance | `cody@10.0.0.227:~/Projects/bark`,    branch `master`, port `8090`, unit `bark.service` |

Both instances are git checkouts; the self-update feature
(`services/update_service.py`) fetches from the configured update remote
(`github` — the GitHub mirror, **only**; no other remotes are consulted),
resets the working tree to `<remote>/<branch>`, installs new
dependencies and exits (systemd `Restart=always` brings it back). Version
shown in the UI is derived from the git commit count — every merged
commit bumps it automatically.

Update channels are `Stable` and `Dev`. `Dev` tracks the `dev` branch;
`Stable` tracks the repo's stable branch — `main` here, resolved from
`config.instance.stable_branch` (`BARK_STABLE_BRANCH`, default `main`),
else the remote
default branch, else `main`. The channel is persisted in
the local git config (`bark.update.channel`) and is **one-way**: once an
instance is on Dev, the API rejects switching back to Stable (403) and the
settings UI disables the Stable option.

## Release gates (all must hold before merging)

1. `dev` is pushed to Forgejo (`git push origin dev`) and the local
   working tree is clean (`git status --short` shows no tracked
   modifications).
2. Full test suite passes on `dev`:
   `cd ~/Projects/bark-dev && .venv/bin/python -m pytest -q`
   (known pre-existing failures, if any, must be named in the merge
   commit message).
3. `dev` is strictly ahead of stable — nothing on `master` that is not
   on `dev`:
   `git rev-list --count origin/master..dev`   # > 0
   `git rev-list --count dev..origin/master`   # must be 0
   If the second count is non-zero, stable has commits dev lacks:
   merge `master` into `dev` first, re-run the tests, then proceed.
4. DB migrations are additive and safe (see `database/migrations/`);
   `init_db` runs pending migrations at startup on both instances.

## Procedure

Run all commands on the dev checkout (`cody@10.0.0.227:~/Projects/bark-dev`)
unless noted.

### 1. Pre-flight

```sh
cd ~/Projects/bark-dev
git status --short                 # no tracked modifications
git fetch origin master dev        # refresh refs
git rev-list --count origin/master..dev   # expect N > 0
git rev-list --count dev..origin/master   # expect 0
.venv/bin/python -m pytest -q      # full suite green
```

### 2. Merge dev into stable (fast-forward)

```sh
git checkout master
git merge --ff-only dev            # fast-forward master to dev HEAD
git push origin master             # Forgejo becomes the new stable
git checkout dev
git push origin dev                # ensure dev ref is current (no-op normally)
```

`--ff-only` guarantees the merge is a pure fast-forward; if it fails,
stable has diverged — go back to gate 3 and reconcile.

### 3. Update the GitHub mirror (manual, owner-only)

The self-updater on both instances pulls from **GitHub** (`main`/`dev`), so
this step is what actually ships releases to the boxes — a release is not
live until the mirror is pushed. The boxes have no GitHub credentials;
push from a machine that does:

```bash
git push github master:main
git push github dev:dev
```

Until the mirror catches up, the instances simply report "no update" — the
no-downgrade guard in `services/update_service.py` refuses any update that
would move a build backwards, so a stale mirror can never downgrade a box.

### 4. Deploy stable to the prod instance

```sh
# as cody on 10.0.0.227
cd ~/Projects/bark
git fetch origin master
git reset --hard origin/master     # prod tracks stable
# as root (via pct exec on pve-geminar, CT 1109):
pct exec 1109 -- systemctl restart bark.service
```

`git reset --hard` is safe here: the prod checkout has no tracked
local modifications (untracked `data/` files — plugins, uploads, DB —
are untouched by reset).

### 5. Deploy dev to the dev instance (if desired)

```sh
cd ~/Projects/bark-dev
git fetch origin dev
git reset --hard origin/dev
pct exec 1109 -- systemctl restart bark-dev.service
```

## Verification (after each deploy)

```sh
# Both instances up and healthy
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8090/   # 200 (prod bark — NOT 8082, that is l3k)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8091/   # 200 (dev bark)

# Instances on the expected commits
cd ~/Projects/bark    && git log --oneline -1   # master == dev HEAD
cd ~/Projects/bark-dev && git log --oneline -1  # dev HEAD

# Clean boot: no tracebacks, migrations applied
pct exec 1109 -- tail -50 /home/cody/Projects/bark/bark.log
sqlite3 ~/Projects/bark/data/bark.db \
  "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 3;"

# Version bump visible (commit-count derived)
curl -s http://127.0.0.1:8090/ | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1
```

Functional spot checks: Discord slash commands respond (`/bark help`),
dashboard login works on both instances, and any feature touched by
the release is exercised on dev first.

## Rollback

Stable rollback (last known-good `master`):

```sh
cd ~/Projects/bark
git log --oneline origin/master -5          # pick the previous good commit
git reset --hard <good-commit>
pct exec 1109 -- systemctl restart bark.service
```

DB migrations are additive and forward-only; a rollback to an older
build keeps the new columns/tables (harmless — new code only reads
what it needs). Never downgrade a schema by hand.

## Release record

Every release is a fast-forward of `master` onto `dev` HEAD. Record in
the merge commit (or release note): date, dev HEAD sha, test result
(counts + any named known failures), deploy shas on both instances,
and mirror status.

## Known issues / notes

- `tests/test_modules/test_slash_commands_smoke.py` asserts plugin
  commands (`/bark serverinfo`, `/bark fact`, `/bark poll`,
  `/bark dice_roller roll`, `/bark trivia start`) only when the
  `bark-plugins` sibling repo is present; a fresh checkout has no
  plugins and only core commands are required.
- The dev instance renders a `DEV VERSION` watermark (dev overlay);
  prod does not. This is intentional.
- The dashboard "Update & Restart" card performs the same
  fetch/reset/restart flow as step 4/5 and is the supported way for an
  owner to self-update from the UI; this process is the CLI equivalent
  and the source of truth for what the UI does. Channel rule (one-way
  Stable → Dev) applies to both paths.
- The live-servers page (`https://bark.warx.org/live-servers`) is a
  separate LAN-only service (`~/Projects/live-servers/live_servers.py`
  on 10.0.0.227:8093, unit `live-servers.service`) — it is NOT part of
  this repo or this release process.
- Tracked files in the checkouts are owned by `cody`; root-owned
  leftovers from earlier root-run operations were cleaned up on
  2026-08-07. If `git status` ever shows a root-owned tracked file,
  `chown cody:cody` it (as container root via `pct exec 1109`).
