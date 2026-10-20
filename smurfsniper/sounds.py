"""Chimes played on one daemon worker thread (never the GUI thread).

WAV bytes are synthesised once and cached; playback uses ``winsound`` with
``SND_MEMORY`` (synchronous on the worker; ``SND_ASYNC`` is not allowed with
``SND_MEMORY``). On non-Windows platforms playing is a no-op.
"""

from __future__ import annotations

import io
import math
import queue
import struct
import threading
import wave

from smurfsniper.logger import logger

_RATE = 44100
# kind -> [(frequency Hz, seconds, volume)]
TONES: dict[str, list[tuple[float, float, float]]] = {
    "one": [(740.0, 0.18, 0.38)],
    "two": [(660.0, 0.20, 0.35), (880.0, 0.20, 0.35)],
    "three": [(587.33, 0.13, 0.34), (880.0, 0.13, 0.34), (1174.66, 0.13, 0.34)],
}


def _tone_frames(freq: float, duration: float, volume: float) -> bytes:
    n = int(_RATE * duration)
    fade = max(1, int(n * 0.05))
    out = bytearray()
    for i in range(n):
        s = math.sin(2 * math.pi * freq * i / _RATE)
        if i < fade:
            s *= i / fade
        elif i > n - fade:
            s *= (n - i) / fade
        out += struct.pack("<h", int(s * volume * 32767))
    return bytes(out)


def render_wav(kind: str) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_RATE)
        for tone in TONES[kind]:
            w.writeframes(_tone_frames(*tone))
    return buf.getvalue()


class SoundPlayer:
    def __init__(self, *, enabled: bool = True):
        self.enabled = enabled
        self._cache: dict[str, bytes] = {}
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def play(self, kind: str) -> None:
        """Queue a chime (``one``, ``two`` or ``three``). Never blocks or raises."""
        if not self.enabled or kind not in TONES:
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="sounds", daemon=True)
            self._thread.start()
        self._queue.put(kind)

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        while True:
            kind = self._queue.get()
            if kind is None:
                return
            try:
                data = self._cache.get(kind)
                if data is None:
                    data = self._cache[kind] = render_wav(kind)
                self._play(data)
            except Exception as e:  # audio is nice-to-have
                logger.debug(f"chime {kind} failed: {e}")

    @staticmethod
    def _play(data: bytes) -> None:
        try:
            import winsound
        except ImportError:
            return
        winsound.PlaySound(data, winsound.SND_MEMORY)
