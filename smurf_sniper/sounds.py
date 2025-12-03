import math
import struct
import tempfile
import wave
import winsound
from pathlib import Path


def write_tone(wav: wave.Wave_write, freq: float, duration: float, volume: float = 0.4):
    sample_rate = 44100
    num_samples = int(sample_rate * duration)

    for i in range(num_samples):
        t = i / sample_rate
        sample = math.sin(2 * math.pi * freq * t)

        fade_samples = int(num_samples * 0.05)
        if i < fade_samples:
            sample *= i / fade_samples
        elif i > num_samples - fade_samples:
            sample *= (num_samples - i) / fade_samples

        sample = int(sample * volume * 32767)
        wav.writeframes(struct.pack("<h", sample))


def two_tone_chime():
    temp_dir = Path(tempfile.gettempdir())
    wav_path = temp_dir / "two_tone_chime.wav"

    if wav_path.exists():
        wav_path.unlink()

    # Two pleasant tones
    tone1 = 660.0  # soft chime A#
    tone2 = 880.0  # harmonic pleasant overtone

    duration1 = 0.20
    duration2 = 0.20

    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        write_tone(wav, tone1, duration1, volume=0.35)

    with wave.open(str(wav_path), "rb") as rf:
        params = rf.getparams()
        frames = rf.readframes(rf.getnframes())

    with wave.open(str(wav_path), "wb") as wav:
        wav.setparams(params)
        wav.writeframes(frames)  # previous tone
        write_tone(wav, tone2, duration2, volume=0.35)

    winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)


if __name__ == "__main__":
    two_tone_chime()
