"""Transcribe batch output to timed turns, and timed turns to named `Turn`s.

The fixture is a real batch job's output for a 59 s two-voice Polly clip; the truth file holds the
script's turns with exact times from sample counts. Transcribe's recognised text differs slightly
from the script, so text is checked against the job's own `audio_segments`.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from commitment_tracker.schemas import Turn
from commitment_tracker.transcription.protocol import TimedTurn
from commitment_tracker.transcription.turns import (
    TranscriptFormatError,
    name_turns,
    to_timed_turns,
)

FIXTURES = Path(__file__).parent / "fixtures"
# Worst errors in the fixture: -632 ms on a start, +684 ms on an end (Transcribe stretches the last
# word of turn 8 into the pause after it).
TOLERANCE_MS = 700


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def output(*items: tuple[str, str | None, str | None, str | None]) -> dict[str, Any]:
    """A minimal job output; each item is (content, start, end, speaker_label), times in seconds.

    An item without a start time is punctuation; a None speaker label leaves the key out.
    """
    built = []
    for content, start, end, speaker in items:
        item: dict[str, Any] = {"alternatives": [{"confidence": "1.0", "content": content}]}
        if start is None:
            item["type"] = "punctuation"
        else:
            item |= {"type": "pronunciation", "start_time": start, "end_time": end}
        if speaker is not None:
            item["speaker_label"] = speaker
        built.append(item)
    return {"jobName": "ct-test", "status": "COMPLETED", "results": {"items": built}}


# --- The captured job ----------------------------------------------------------------------------


def test_fixture_turns_match_the_script() -> None:
    truth = load("transcribe-output.truth.json")["turns"]
    turns = to_timed_turns(load("transcribe-output.json"))

    assert len(turns) == len(truth)
    speaker_of = {"A": 0, "B": 1}
    for got, want in zip(turns, truth, strict=True):
        assert got.speaker == speaker_of[want["speaker"]]
        assert abs(got.start_ms - want["start_ms"]) <= TOLERANCE_MS
        assert abs(got.end_ms - want["end_ms"]) <= TOLERANCE_MS


def test_fixture_text_matches_the_segments_per_speaker_run() -> None:
    # Transcribe split one of B's turns into two segments; a turn is a run of one speaker's words.
    segments = load("transcribe-output.json")["results"]["audio_segments"]
    runs: list[list[str]] = []
    previous = None
    for segment in segments:
        if segment["speaker_label"] != previous:
            runs.append([])
            previous = segment["speaker_label"]
        runs[-1].append(segment["transcript"])

    turns = to_timed_turns(load("transcribe-output.json"))

    assert len(segments) == len(turns) + 1
    assert [turn.text for turn in turns] == [" ".join(run) for run in runs]


# --- Grouping, punctuation and times -------------------------------------------------------------


def test_groups_consecutive_words_and_attaches_punctuation() -> None:
    turns = to_timed_turns(
        output(
            ("Hello", "0.05", "0.4", "spk_0"),
            (",", None, None, "spk_0"),
            ("there", "0.4", "0.81", "spk_0"),
            (".", None, None, "spk_0"),
            ("Hi", "1.2", "1.5", "spk_1"),
            ("!", None, None, "spk_1"),
            ("Bye", "2.0", "2.3", "spk_0"),
        )
    )

    assert turns == [
        TimedTurn(speaker=0, text="Hello, there.", start_ms=50, end_ms=810),
        TimedTurn(speaker=1, text="Hi!", start_ms=1200, end_ms=1500),
        TimedTurn(speaker=0, text="Bye", start_ms=2000, end_ms=2300),
    ]


def test_punctuation_sticks_to_the_previous_word_whatever_its_label() -> None:
    turns = to_timed_turns(
        output(
            ("Done", "0.0", "0.3", "spk_0"),
            (".", None, None, "spk_1"),
            ("Great", "0.5", "0.9", "spk_1"),
        )
    )

    assert [turn.text for turn in turns] == ["Done.", "Great"]


def test_speakers_are_numbered_in_order_of_first_speech() -> None:
    turns = to_timed_turns(
        output(
            ("One", "0.0", "0.2", "spk_1"),
            ("Two", "0.3", "0.5", "spk_0"),
            ("Three", "0.6", "0.8", "spk_2"),
            ("Four", "0.9", "1.0", "spk_1"),
        )
    )

    assert [turn.speaker for turn in turns] == [0, 1, 2, 0]


def test_rounds_seconds_to_milliseconds() -> None:
    (turn,) = to_timed_turns(output(("Hi", "1.0005", "2.0015", "spk_0")))

    assert (turn.start_ms, turn.end_ms) == (1000, 2002)


def test_output_without_speaker_labels_is_one_speaker() -> None:
    turns = to_timed_turns(output(("Just", "0.0", "0.2", None), ("me", "0.3", "0.5", None)))

    assert turns == [TimedTurn(speaker=0, text="Just me", start_ms=0, end_ms=500)]


@pytest.mark.parametrize(
    "items",
    [
        (),
        ((".", None, None, "spk_0"),),
    ],
    ids=["no items", "only punctuation"],
)
def test_no_words_means_no_turns(
    items: tuple[tuple[str, str | None, str | None, str | None]],
) -> None:
    assert to_timed_turns(output(*items)) == []


def test_leading_punctuation_is_dropped() -> None:
    turns = to_timed_turns(output(("?", None, None, "spk_0"), ("Yes", "0.1", "0.4", "spk_0")))

    assert [turn.text for turn in turns] == ["Yes"]


# --- Malformed output ----------------------------------------------------------------------------


def broken(change: str) -> object:
    good = output(("Secret", "0.0", "0.4", "spk_0"))
    item = good["results"]["items"][0]
    match change:
        case "no results":
            return {"jobName": "ct-test"}
        case "no start time":
            del item["start_time"]
        case "bad time":
            item["end_time"] = "soon"
        case "negative time":
            item["start_time"] = "-1.0"
        case "end before start":
            item["end_time"] = "0.0"
            item["start_time"] = "0.4"
        case "no alternatives":
            item["alternatives"] = []
        case "unknown type":
            item["type"] = "speech"
    return good


@pytest.mark.parametrize(
    "change",
    [
        "no results",
        "no start time",
        "bad time",
        "negative time",
        "end before start",
        "no alternatives",
        "unknown type",
    ],
)
def test_malformed_output_raises_without_its_text(change: str) -> None:
    with pytest.raises(TranscriptFormatError) as caught:
        to_timed_turns(broken(change))

    assert "Secret" not in str(caught.value)


# --- Names ---------------------------------------------------------------------------------------

TIMED = [
    TimedTurn(speaker=0, text="Hello.", start_ms=0, end_ms=400),
    TimedTurn(speaker=1, text="Hi.", start_ms=500, end_ms=800),
    TimedTurn(speaker=0, text="Bye.", start_ms=900, end_ms=1200),
]


def test_names_map_to_speakers_in_order_of_first_speech() -> None:
    assert name_turns(TIMED, ["Dana", "Lee"]) == [
        Turn(speaker="Dana", text="Hello.", start_ms=0, end_ms=400),
        Turn(speaker="Lee", text="Hi.", start_ms=500, end_ms=800),
        Turn(speaker="Dana", text="Bye.", start_ms=900, end_ms=1200),
    ]


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ([], ["Speaker 1", "Speaker 2", "Speaker 1"]),
        (["Dana"], ["Dana", "Speaker 2", "Dana"]),
    ],
)
def test_missing_names_default_to_numbered_speakers(names: list[str], expected: list[str]) -> None:
    assert [turn.speaker for turn in name_turns(TIMED, names)] == expected


def test_a_third_speaker_gets_a_numbered_name() -> None:
    third = [*TIMED, TimedTurn(speaker=2, text="Me too.", start_ms=1300, end_ms=1600)]

    assert name_turns(third, ["Dana", "Lee"])[-1].speaker == "Speaker 3"


def test_fixture_turns_are_valid_request_turns() -> None:
    turns = name_turns(to_timed_turns(load("transcribe-output.json")), ["Alex", "Sam"])

    assert [turn.speaker for turn in turns[:3]] == ["Alex", "Sam", "Alex"]
    assert all(isinstance(turn, Turn) and turn.start_ms is not None for turn in turns)
