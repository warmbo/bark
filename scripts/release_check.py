#!/usr/bin/env python3
"""Release gate — every check that must be green before promoting dev -> stable.

Codifies the release expectation so a promotion is a command, not a judgement
call: lint, format, types, tests, security scan, dependency audit, generated
assets, and a clean working tree. `--allow-dirty` exists only for a deliberate
in-progress check.

    .venv/bin/python scripts/release_check.py
    .venv/bin/python scripts/release_check.py --quick   # skip the slow audit pair

Exit code 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
TYPED_TARGETS = [
    "bot",
    "dashboard",
    "database",
    "services",
    "modules",
    "app.py",
    "config.py",
    "bark_version.py",
]


def _tool(name: str) -> list[str]:
    """Prefer the venv console script, else fall back to ``python -m <name>``.

    Some tools ship only a console script (pip-audit is not importable as a
    module in this venv), so ``-m`` alone reports a false failure.
    """
    exe = ROOT / ".venv" / "bin" / name
    return [str(exe)] if exe.exists() else [PY, "-m", name]


def _checks(quick: bool) -> list[tuple[str, list[str], Path]]:
    checks: list[tuple[str, list[str], Path]] = [
        ("pytest", [*_tool("pytest"), "-q"], ROOT),
        ("ruff lint", [*_tool("ruff"), "check", "."], ROOT),
        ("ruff format", [*_tool("ruff"), "format", "--check", "."], ROOT),
        ("mypy", [*_tool("mypy"), *TYPED_TARGETS], ROOT),
    ]
    if not quick:
        checks += [
            (
                "bandit",
                [
                    *_tool("bandit"),
                    "-q",
                    "-r",
                    "-ll",
                    "bot",
                    "dashboard",
                    "database",
                    "services",
                    "modules",
                    "app.py",
                    "config.py",
                ],
                ROOT,
            ),
            ("pip-audit", _tool("pip-audit"), ROOT),
        ]
    # Generated frontend assets must reproduce from source (npm run check
    # rebuilds and diffs the committed CSS/fonts/vendor).
    if shutil.which("npm") and (ROOT / "frontend" / "node_modules").is_dir():
        checks.append(("frontend assets", ["npm", "run", "--silent", "check"], ROOT / "frontend"))
    return checks


def _dirty_files() -> list[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [line for line in out.splitlines() if line.strip() and not line.startswith("??")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip bandit + pip-audit")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="do not fail on uncommitted changes (in-progress checks only)",
    )
    args = parser.parse_args()

    if not Path(PY).exists():
        print(f"✗ no interpreter at {PY} — activate the venv or install the dev extras")
        return 2

    results: list[tuple[str, bool, str]] = []
    for name, cmd, cwd in _checks(args.quick):
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()
        results.append((name, proc.returncode == 0, tail[-1] if tail else ""))

    dirty = _dirty_files()
    tree_ok = args.allow_dirty or not dirty

    print("\nBark release gate\n" + "=" * 60)
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:18} {detail[:70]}")
    print(f"  {'PASS' if tree_ok else 'FAIL'}  {'working tree':18} ", end="")
    print(
        "clean"
        if tree_ok
        else f"{len(dirty)} uncommitted file(s): {', '.join(d[:40] for d in dirty[:3])}"
    )

    failed = [name for name, ok, _ in results if not ok] + ([] if tree_ok else ["working tree"])
    if failed:
        print(f"\n✗ NOT RELEASABLE — {', '.join(failed)}")
        return 1
    print("\n✓ all gates green — safe to promote")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
