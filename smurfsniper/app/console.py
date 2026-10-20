"""Console attachment for the windowed (``console=False``) frozen exe."""

from __future__ import annotations

import sys


def attach_parent_console() -> bool:
    """Let ``smurfsniper.exe --version`` print into the terminal that launched it.

    Only acts in a frozen build started with arguments and without a stdout. Output may
    appear after the shell prompt returns; that is a Windows GUI-subsystem limitation.
    """
    try:
        if not getattr(sys, "frozen", False) or len(sys.argv) <= 1 or sys.stdout is not None:
            return False
        import ctypes

        if not ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            return False
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
        return True
    except Exception:
        return False
