"""WAV validation: the server's check that an upload is 16 kHz mono PCM of at most 60 seconds."""

import struct

import pytest

from commitment_tracker.jobs.audio import (
    MAX_AUDIO_BYTES,
    AudioInvalid,
    AudioTooLong,
    validate_wav,
)
from tests.wav import make_wav


def test_a_one_second_clip_reports_its_duration() -> None:
    assert validate_wav(make_wav(1.0)).duration_ms == 1000


def test_sixty_seconds_is_the_limit_and_fills_the_upload_cap() -> None:
    data = make_wav(60.0)
    assert len(data) == MAX_AUDIO_BYTES
    assert validate_wav(data).duration_ms == 60_000


def test_a_clip_over_sixty_seconds_is_too_long() -> None:
    with pytest.raises(AudioTooLong):
        validate_wav(make_wav(60.5))


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not audio at all",
        b"RIFF" + b"\x00" * 40,
        make_wav(1.0)[:30],  # cut inside the header
        make_wav(0.0),  # no samples
    ],
    ids=["empty", "text", "zeroed-header", "truncated-header", "silent-zero-length"],
)
def test_malformed_audio_is_invalid(data: bytes) -> None:
    with pytest.raises(AudioInvalid):
        validate_wav(data)


@pytest.mark.parametrize(
    ("rate", "channels", "width"),
    [(44_100, 1, 2), (16_000, 2, 2), (16_000, 1, 1), (8_000, 1, 2)],
    ids=["44.1kHz", "stereo", "8-bit", "8kHz"],
)
def test_other_formats_are_invalid(rate: int, channels: int, width: int) -> None:
    with pytest.raises(AudioInvalid):
        validate_wav(make_wav(1.0, rate=rate, channels=channels, width=width))


def test_a_header_claiming_more_audio_than_the_file_holds_is_invalid() -> None:
    data = bytearray(make_wav(1.0))
    struct.pack_into("<I", data, 40, 3_200_000)  # data chunk size, far past the end
    with pytest.raises(AudioInvalid):
        validate_wav(bytes(data))


def test_a_header_claiming_less_audio_than_the_file_holds_is_invalid() -> None:
    """The duration must come from the bytes Transcribe will read, not only from the header."""
    data = bytearray(make_wav(61.0))
    struct.pack_into("<I", data, 40, 32_000)  # claims one second
    with pytest.raises(AudioInvalid):
        validate_wav(bytes(data))


def test_errors_carry_no_audio_bytes() -> None:
    with pytest.raises(AudioInvalid) as caught:
        validate_wav(b"secret-bytes")
    assert "secret" not in str(caught.value)
