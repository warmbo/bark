"""Application version contract tests."""

from importlib.metadata import version

from bark_version import __version__


def test_runtime_version_matches_installed_package_metadata():
    assert __version__ == version("bark")
