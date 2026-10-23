"""A WAV builder for tests."""

import io
import wave


def make_wav(
    seconds: float = 1.0, *, rate: int = 16_000, channels: int = 1, width: int = 2
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return buffer.getvalue()
