"""PyInstaller entry point for the frozen Windows exe.

A thin wrapper so the bundled binary launches the Click CLI exactly like the
`smurfsniper` console script does. Kept out of the package so it is only used
by the freeze step.
"""

from smurfsniper.cli import main

if __name__ == "__main__":
    main()
