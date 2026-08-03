"""Distribution packaging contracts."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_web_assets_are_included_in_wheels():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assets = config["tool"]["setuptools"]["package-data"]["dashboard"]
    assert "templates/**/*.html" in assets
    assert "static/**/*" in assets
