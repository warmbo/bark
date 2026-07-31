"""Runtime access to Bark's installed package version."""

from importlib.metadata import version

__version__ = version("bark")
