"""Scoring the audio set (ADR 0010): transcribe each clip, align it to its item, score, compare.

1. Transcribe: each clip goes through Amazon Transcribe (batch, two speaker labels) once; the turns
   are cached by the audio's SHA-256 under eval/.cache/transcripts/, so every configuration after
   the first reads them for free. Evaluation jobs are named `eval-...`, never `ct-...`: the stack's
   EventBridge rule hands `ct-` jobs to the demo worker.
2. Align: transcribed turns map to item turns in order, by shared words (difflib over
   words), and each transcribed speaker number maps to the role it most often aligns with. An
   expected span moves to the transcribed turn, among those aligned to its original turn, that
   holds most of its quote's words; a span whose turn vanished points at no turn and counts as a
   miss. The quotes stay as written: the word-overlap matching (>= 0.6) already tolerates small ASR
   differences, so the aligned item is built without the substring check.
3. Score: the extractor runs on the aligned items, and on the same items as text. The penalty is
   ledger F1 on audio minus ledger F1 on text, per source (polly, human) and overall. Turn-count
   mismatches, speaker errors and unmatched spans are counted on their own, so alignment trouble
   is visible rather than silently scored as extraction errors.
"""

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from commitment_tracker.evaluation.audio import AudioClip
from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.matching import WORD, overlap
from commitment_tracker.evaluation.metrics import compute_scores
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.schemas import Turn
from commitment_tracker.transcription.protocol import TimedTurn
from commitment_tracker.transcription.turns import to_timed_turns

# backend/src/commitment_tracker/evaluation/audio_eval.py -> backend/eval/.cache/transcripts
TRANSCRIPTS_DIR = Path(__file__).resolve().parents[3] / "eval" / ".cache" / "transcripts"
NO_TURN = -1  # where an expected span points when its turn was not transcribed
JOB_PREFIX = "eval-"
SAMPLE_RATE_HZ = 16_000


class Transcribe(Protocol):
    def __call__(self, clip: AudioClip) -> list[TimedTurn]: ...


class TranscriptCache:
    def __init__(self, directory: Path = TRANSCRIPTS_DIR) -> None:
        self.directory = directory

    def _path(self, sha256: str) -> Path:
        return self.directory / f"{sha256}.json"

    def get(self, sha256: str) -> list[TimedTurn] | None:
        path = self._path(sha256)
        if not path.is_file():
            return None
        return [TimedTurn(**turn) for turn in json.loads(path.read_text(encoding="utf-8"))]

    def put(self, sha256: str, turns: list[TimedTurn]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        data = [turn.__dict__ for turn in turns]
        self._path(sha256).write_bytes(json.dumps(data, indent=2).encode("utf-8"))


class AwsClipTranscriber:
    """One Transcribe batch job per clip, polled to completion, its output removed afterwards."""

    def __init__(
        self,
        transcribe: Any,
        s3: Any,
        bucket: str,
        *,
        poll_seconds: float = 5.0,
        timeout_seconds: float = 900.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transcribe = transcribe
        self._s3 = s3
        self._bucket = bucket
        self._poll = poll_seconds
        self._timeout = timeout_seconds
        self._sleep = sleep

    def __call__(self, clip: AudioClip) -> list[TimedTurn]:
        name = f"{JOB_PREFIX}{clip.sha256[:24]}"
        key = f"transcripts/{name}.json"
        self._transcribe.start_transcription_job(
            TranscriptionJobName=name,
            LanguageCode="en-US",
            MediaFormat="wav",
            MediaSampleRateHertz=SAMPLE_RATE_HZ,
            Media={"MediaFileUri": f"s3://{self._bucket}/{clip.key}"},
            OutputBucketName=self._bucket,
            OutputKey=key,
            Settings={"ShowSpeakerLabels": True, "MaxSpeakerLabels": 2},
        )
        waited = 0.0
        while True:
            job = self._transcribe.get_transcription_job(TranscriptionJobName=name)
            status = job["TranscriptionJob"]["TranscriptionJobStatus"]
            if status == "COMPLETED":
                break
            if status == "FAILED":
                reason = job["TranscriptionJob"].get("FailureReason", "unknown")
                raise RuntimeError(f"transcription of {clip.test_item_id} failed: {reason}")
            if waited >= self._timeout:
                raise RuntimeError(f"transcription of {clip.test_item_id} timed out")
            self._sleep(self._poll)
            waited += self._poll
        body = self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        turns = to_timed_turns(json.loads(body))
        # The turns are cached locally; the job and its output aren't needed again.
        self._transcribe.delete_transcription_job(TranscriptionJobName=name)
        self._s3.delete_object(Bucket=self._bucket, Key=key)
        return turns


@dataclass(frozen=True)
class Alignment:
    item: EvalItem  # transcribed turns with role names, expected spans moved onto them
    turn_mismatch: bool
    speaker_errors: int
    unmatched_spans: int


def _words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def _shared(a: list[str], b: list[str]) -> int:
    return sum(block.size for block in SequenceMatcher(None, a, b).get_matching_blocks())


def _score(a: list[str], b: list[str]) -> float:
    """Shared words, plus how much of the longer turn they cover, so "Okay." prefers "Okay."."""
    shared = _shared(a, b)
    return shared + shared / max(len(a), len(b)) if shared else 0.0


def _in_order(scores: list[list[float]]) -> list[int]:
    """The best mapping of transcribed turns to item turns that never goes backwards: each turn maps
    to the same item turn as the previous one (a split) or a later one, or to none. Dynamic
    programming over the highest item turn used so far; the inputs are a few dozen turns."""
    if not scores or not scores[0]:
        return [NO_TURN] * len(scores)
    turns = len(scores[0])
    unreachable = float("-inf")
    best = [0.0] + [unreachable] * turns  # best[k]: total so far with item turn k - 1 the latest
    steps: list[list[tuple[int, int]]] = []
    for row in scores:
        new = [unreachable] * (turns + 1)
        step = [(0, NO_TURN)] * (turns + 1)
        for state, total in enumerate(best):
            if total == unreachable:
                continue
            if total > new[state]:  # this transcribed turn maps to no item turn
                new[state], step[state] = total, (state, NO_TURN)
            for target in range(max(state - 1, 0), turns):
                if row[target] > 0 and total + row[target] > new[target + 1]:
                    new[target + 1], step[target + 1] = total + row[target], (state, target)
        steps.append(step)
        best = new
    state = max(range(turns + 1), key=lambda k: best[k])
    mapped = [NO_TURN] * len(scores)
    for index in range(len(scores) - 1, -1, -1):
        state, mapped[index] = steps[index][state]
    return mapped


def align(item: EvalItem, transcribed: list[TimedTurn]) -> Alignment:
    item_words = [_words(turn.text) for turn in item.turns]
    scores = [[_score(_words(t.text), other) for other in item_words] for t in transcribed]
    mapped = _in_order(scores)  # item turn index for each transcribed turn, or NO_TURN

    votes: dict[int, Counter[str]] = {}
    for turn, target in zip(transcribed, mapped, strict=True):
        if target != NO_TURN:
            votes.setdefault(turn.speaker, Counter())[item.turns[target].speaker] += 1
    roles = {speaker: count.most_common(1)[0][0] for speaker, count in votes.items()}

    turns = [
        Turn(
            speaker=roles.get(turn.speaker, f"speaker {turn.speaker}"),
            text=turn.text,
            start_ms=turn.start_ms,
            end_ms=turn.end_ms,
        )
        for turn in transcribed
    ]
    speaker_errors = sum(
        target != NO_TURN and turns[i].speaker != item.turns[target].speaker
        for i, target in enumerate(mapped)
    )

    expected = []
    unmatched = 0
    for span in item.expected:
        candidates = [i for i, target in enumerate(mapped) if target == span.turn_index]
        quote_words = _words(span.quote)
        if candidates:
            new_index = max(
                candidates,
                key=lambda i: (
                    _shared(quote_words, _words(turns[i].text)),
                    overlap(span.quote, turns[i].text),
                ),
            )
        else:
            new_index, unmatched = NO_TURN, unmatched + 1
        expected.append(span.model_copy(update={"turn_index": new_index}))

    # Built without validation: quotes are compared by word overlap, not as substrings, here.
    aligned = EvalItem.model_construct(**{**dict(item), "turns": turns, "expected": expected})
    return Alignment(
        item=aligned,
        turn_mismatch=len(transcribed) != len(item.turns),
        speaker_errors=speaker_errors,
        unmatched_spans=unmatched,
    )


class AudioSlice(BaseModel):
    clips: int
    ledger_f1_audio: float
    ledger_f1_text: float
    penalty: float  # audio minus text: negative means transcription cost accuracy


class AudioScores(BaseModel):
    slices: dict[str, AudioSlice]  # "polly", "human" and "all"
    turn_mismatches: int
    speaker_errors: int
    unmatched_spans: int
    text_set_sha256: str


def audio_scores(
    clips: dict[str, AudioClip],
    alignments: dict[str, Alignment],
    audio_results: list[ItemResult],
    text_results: list[ItemResult],
    *,
    text_sha256: str,
) -> AudioScores:
    text_by_id = {r.item.id: r for r in text_results}
    groups: dict[str, list[str]] = {"all": [r.item.id for r in audio_results]}
    for result in audio_results:
        groups.setdefault(clips[result.item.id].source, []).append(result.item.id)
    audio_by_id = {r.item.id: r for r in audio_results}
    slices = {}
    for name in sorted(groups, key=lambda n: (n == "all", n)):
        ids = groups[name]
        audio_f1 = compute_scores([audio_by_id[i] for i in ids]).ledger.f1
        text_f1 = compute_scores([text_by_id[i] for i in ids]).ledger.f1
        slices[name] = AudioSlice(
            clips=len(ids),
            ledger_f1_audio=audio_f1,
            ledger_f1_text=text_f1,
            penalty=audio_f1 - text_f1,
        )
    return AudioScores(
        slices=slices,
        turn_mismatches=sum(a.turn_mismatch for a in alignments.values()),
        speaker_errors=sum(a.speaker_errors for a in alignments.values()),
        unmatched_spans=sum(a.unmatched_spans for a in alignments.values()),
        text_set_sha256=text_sha256,
    )
