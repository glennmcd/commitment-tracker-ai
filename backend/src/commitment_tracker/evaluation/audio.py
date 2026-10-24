"""Evaluation audio (ADR 0010): clips of test items, pinned in eval/sets/audio/clips.jsonl.

Each clip speaks one item of the audio set's source set (`items_from`, normally `test`). Polly clips
are made from the script with two standard voices and can be regenerated; human clips are two
people reading the script into the demo's recorder and can only be fetched. A clip is recorded by
item id, source, the voice or reader behind each speaker role (reader ids like `reader-1`, never
names), duration and SHA-256. The WAVs live in a private bucket and in eval/.audio/ (git-ignored)
once fetched; every transfer checks the hash.
"""

import hashlib
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field

from commitment_tracker.evaluation.dataset import EvalItem, jsonl_lines
from commitment_tracker.evaluation.sets import SETS_DIR, load_manifest, load_set, set_dir
from commitment_tracker.evaluation.synthesis import (
    Synthesizer,
    assign_voices,
    build_clip,
    wav_bytes,
)
from commitment_tracker.jobs.audio import AudioInvalid, AudioTooLong, validate_wav

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

# backend/src/commitment_tracker/evaluation/audio.py -> backend/eval/.audio (git-ignored)
AUDIO_DIR = Path(__file__).resolve().parents[3] / "eval" / ".audio"
AUDIO_SET = "audio"
DEFAULT_VOICES = ("Joanna", "Matthew")
READER = re.compile(r"reader-[0-9]+")


class AudioSetError(ValueError):
    pass


class AudioClip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_item_id: str = Field(min_length=1)
    source: Literal["polly", "human"]
    voices: dict[str, str]  # speaker role -> Polly voice, or -> reader id for a human clip
    duration_ms: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def key(self) -> str:
        return f"clips/{self.test_item_id}.wav"

    @property
    def filename(self) -> str:
        return f"{self.test_item_id}.wav"


class ClipStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes | None: ...


class S3ClipStore:
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType="audio/wav")

    def get(self, key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return None
            raise
        return response["Body"].read()


def _clips_path(root: Path) -> Path:
    return set_dir(AUDIO_SET, root) / "clips.jsonl"


def load_clips(root: Path = SETS_DIR) -> list[AudioClip]:
    path = _clips_path(root)
    lines = jsonl_lines(path) if path.is_file() else []
    return [AudioClip.model_validate_json(line) for line in lines if line.strip()]


def _write_clips(root: Path, clips: list[AudioClip]) -> None:
    ordered = sorted(clips, key=lambda clip: clip.test_item_id)
    text = "".join(clip.model_dump_json() + "\n" for clip in ordered)
    _clips_path(root).write_bytes(text.encode("utf-8"))


def source_items(root: Path = SETS_DIR) -> dict[str, EvalItem]:
    """The items the audio set's clips speak, from the set its manifest names."""
    manifest = load_manifest(AUDIO_SET, root)
    if manifest.kind != "audio" or not manifest.items_from:
        raise AudioSetError("eval/sets/audio/set.json must be kind audio with items_from")
    return {item.id: item for item in load_set(manifest.items_from, root, allow_empty=True).items}


def _two_speaker_item(items: dict[str, EvalItem], item_id: str, source_set: str) -> EvalItem:
    if item_id not in items:
        raise AudioSetError(f"{item_id} is not in {source_set}")
    item = items[item_id]
    if len({turn.speaker for turn in item.turns}) != 2:
        raise AudioSetError(f"{item_id} needs exactly two speakers for a two-voice clip")
    return item


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replace(clips: list[AudioClip], clip: AudioClip) -> list[AudioClip]:
    return [c for c in clips if c.test_item_id != clip.test_item_id] + [clip]


def make_polly(
    item_ids: Sequence[str],
    root: Path,
    audio_dir: Path,
    synthesize: Synthesizer,
    *,
    voices: tuple[str, str] = DEFAULT_VOICES,
) -> list[AudioClip]:
    """Speak each item with Polly into audio_dir and pin the clips; never replaces a human clip."""
    items = source_items(root)
    source_set = load_manifest(AUDIO_SET, root).items_from or "?"
    clips = load_clips(root)
    human = {c.test_item_id for c in clips if c.source == "human"}
    made: list[AudioClip] = []
    pending: dict[str, bytes] = {}
    for item_id in item_ids:
        if item_id in human:
            raise AudioSetError(f"{item_id} has a human recording; Polly won't replace it")
        item = _two_speaker_item(items, item_id, source_set)
        assignment = assign_voices(item.turns, voices)
        spoken = build_clip(item_id, item.turns, assignment, synthesize)
        data = wav_bytes(spoken.pcm)
        pending[item_id] = data
        made.append(
            AudioClip(
                test_item_id=item_id,
                source="polly",
                voices=assignment,
                duration_ms=spoken.duration_ms,
                sha256=_sha256(data),
            )
        )
    # Write only once every clip is made, so a Polly failure leaves the manifest as it was.
    audio_dir.mkdir(parents=True, exist_ok=True)
    for clip in made:
        (audio_dir / clip.filename).write_bytes(pending[clip.test_item_id])
        clips = _replace(clips, clip)
    _write_clips(root, clips)
    return made


def add_human(
    item_id: str, wav: Path, readers: dict[str, str], root: Path, audio_dir: Path
) -> AudioClip:
    """Pin a recording of an item read by two people, named only as reader ids."""
    items = source_items(root)
    item = _two_speaker_item(items, item_id, load_manifest(AUDIO_SET, root).items_from or "?")
    if any(not READER.fullmatch(reader) for reader in readers.values()):
        raise AudioSetError("readers are recorded as reader-<n>, never by name")
    if set(readers) != {turn.speaker for turn in item.turns}:
        raise AudioSetError("give a reader for every speaker role in the item")
    if len(set(readers.values())) != 2:
        raise AudioSetError("a human clip needs two different readers")
    data = wav.read_bytes()
    try:
        info = validate_wav(data)
    except (AudioInvalid, AudioTooLong) as error:
        raise AudioSetError(f"{wav.name}: {error}") from None
    clip = AudioClip(
        test_item_id=item_id,
        source="human",
        voices=dict(sorted(readers.items())),
        duration_ms=info.duration_ms,
        sha256=_sha256(data),
    )
    audio_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wav, audio_dir / clip.filename)
    _write_clips(root, _replace(load_clips(root), clip))
    return clip


def upload(root: Path, audio_dir: Path, store: ClipStore) -> list[str]:
    """Push every clip present locally; a local file that doesn't match its hash is refused."""
    uploaded = []
    for clip in load_clips(root):
        path = audio_dir / clip.filename
        if not path.is_file():
            continue
        data = path.read_bytes()
        if _sha256(data) != clip.sha256:
            raise AudioSetError(f"{clip.test_item_id}: local file doesn't match its sha256")
        store.put(clip.key, data)
        uploaded.append(clip.test_item_id)
    return uploaded


def fetch(root: Path, audio_dir: Path, store: ClipStore) -> list[str]:
    """Download clips that are missing or stale locally, checking every hash."""
    fetched = []
    audio_dir.mkdir(parents=True, exist_ok=True)
    for clip in load_clips(root):
        path = audio_dir / clip.filename
        if path.is_file() and _sha256(path.read_bytes()) == clip.sha256:
            continue
        data = store.get(clip.key)
        if data is None:
            raise AudioSetError(f"{clip.test_item_id} is not in the bucket; upload it first")
        if _sha256(data) != clip.sha256:
            raise AudioSetError(f"{clip.test_item_id}: the bucket's copy doesn't match its sha256")
        path.write_bytes(data)
        fetched.append(clip.test_item_id)
    return fetched


def parse_readers(text: str) -> dict[str, str]:
    """`seller=reader-1,buyer=reader-2` -> {"seller": "reader-1", "buyer": "reader-2"}."""
    pairs = [part.split("=", 1) for part in text.split(",") if part.strip()]
    if any(len(pair) != 2 for pair in pairs):
        raise AudioSetError("readers look like seller=reader-1,buyer=reader-2")
    return {role.strip(): reader.strip() for role, reader in pairs}
