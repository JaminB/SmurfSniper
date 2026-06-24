"""Single runtime source of truth for the app version.

Default is a dev placeholder. The release CI (.github/workflows/build-windows.yml)
overwrites this file with the version string supplied at trigger time before
building the frozen exe.
"""

__version__ = "0.0.0+dev"
