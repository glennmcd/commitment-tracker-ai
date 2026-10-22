"""Server-side check of an uploaded clip: 16 kHz mono 16-bit PCM WAV, at most 60 seconds.

The browser writes exactly this format, so the size cap on the presigned upload also caps the
duration; this check keeps the server from trusting the browser. The file must be the canonical
44-byte header followed by the samples, so the duration read from the header is the duration of the
bytes Transcribe will read. Errors never carry bytes from the file.
"""

import io
import struct
import wave
from dataclasses import dataclass

SAMPLE_RATE_HZ = 16_000
SAMPLE_WIDTH_BYTES = 2
CHANNELS = 1
MAX_AUDIO_SECONDS = 60
HEADER_BYTES = 44
BYTES_PER_SECOND = SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES * CHANNELS
# 60 s of samples plus the header: the content-length cap of the presigned upload.
MAX_AUDIO_BYTES = MAX_AUDIO_SECONDS * BYTES_PER_SECOND + HEADER_BYTES


class AudioInvalid(ValueError):
    """The file is not a WAV in the accepted format."""


class AudioTooLong(ValueError):
    """The clip is longer than MAX_AUDIO_SECONDS."""


@dataclass(frozen=True)
class AudioInfo:
    duration_ms: int


def validate_wav(data: bytes) -> AudioInfo:
    try:
        with wave.open(io.BytesIO(data), "rb") as clip:
            rate = clip.getframerate()
            channels = clip.getnchannels()
            width = clip.getsampwidth()
            frames = clip.getnframes()
    except (wave.Error, EOFError, struct.error):
        raise AudioInvalid("the file is not a readable WAV") from None
    if (rate, channels, width) != (SAMPLE_RATE_HZ, CHANNELS, SAMPLE_WIDTH_BYTES):
        raise AudioInvalid("the WAV must be 16 kHz mono 16-bit PCM")
    if frames == 0:
        raise AudioInvalid("the WAV has no samples")
    if len(data) != HEADER_BYTES + frames * SAMPLE_WIDTH_BYTES * CHANNELS:
        raise AudioInvalid("the WAV header does not match the file size")
    if frames > MAX_AUDIO_SECONDS * SAMPLE_RATE_HZ:
        raise AudioTooLong(f"the clip is longer than {MAX_AUDIO_SECONDS} seconds")
    return AudioInfo(duration_ms=frames * 1000 // SAMPLE_RATE_HZ)
