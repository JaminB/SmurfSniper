"""PyInstaller entry point for the frozen Windows exe.

A thin wrapper so the bundled binary launches the Click CLI exactly like the
`smurfsniper` console script does. Kept out of the package so it is only used
by the freeze step. The exe is a windowed (no console) build, so it first tries to
attach to the console of the terminal that launched it.
"""

from smurfsniper.app.console import attach_parent_console
from smurfsniper.cli import main

if __name__ == "__main__":
    attach_parent_console()
    main()
