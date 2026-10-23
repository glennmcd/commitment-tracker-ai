"""POST /jobs, GET /jobs/{id} and GET /samples through the TestClient, on fakes."""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from commitment_tracker.api.app import create_app
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.jobs.memory import MemoryJobStore
from commitment_tracker.jobs.record import JobStatus, JobUpdate
from commitment_tracker.jobs.samples import SampleCatalog, SampleClip
from commitment_tracker.jobs.service import JobService
from commitment_tracker.schemas import Turn
from commitment_tracker.transcription.fake import FakeTranscriber
from tests.fakes import FakeAdapter, FakeAudioStore, FakeDispatcher
from tests.test_jobs import analysis
from tests.wav import make_wav

SECRET = "pricing-is-42"
UPLOAD_ID = "a" * 32
KEY = f"uploads/{UPLOAD_ID}.wav"
SAMPLE = SampleClip(id="invoice", title="Resending an invoice", duration_ms=41_500, sha256="b" * 64)
NOW = 1_761_000_000.0
AUDIO_BODY: dict[str, Any] = {
    "upload_id": UPLOAD_ID,
    "call_date": "2026-10-21",
    "speaker_names": ["Ana", "Ben"],
}
TEXT_BODY: dict[str, Any] = {
    "transcript": [
        {"speaker": "Ana", "text": f"I will send {SECRET}."},
        {"speaker": "Ben", "text": "Thanks."},
    ],
    "call_date": "2026-10-21",
}


class Rig:
    def __init__(self, *, with_service: bool = True) -> None:
        self.audio = FakeAudioStore()
        self.store = MemoryJobStore(clock=lambda: NOW)
        self.transcriber = FakeTranscriber()
        self.dispatcher = FakeDispatcher()
        service = JobService(
            self.store,
            self.audio,
            self.transcriber,
            SampleCatalog([SAMPLE]),
            self.dispatcher,
            clock=lambda: NOW,
        )
        extractor = Extractor(FakeAdapter(), load_prompt("v1"))
        self.client = TestClient(
            create_app(extractor=extractor, jobs=service if with_service else None)
        )


# --- POST /jobs ----------------------------------------------------------------------------------


def test_an_upload_job_is_accepted_and_transcribing() -> None:
    rig = Rig()
    rig.audio.put(KEY, make_wav(2.0))

    response = rig.client.post("/jobs", json=AUDIO_BODY)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "transcribing"
    assert len(body["job_id"]) == 64
    assert body["transcript"] is None
    assert body["analysis"] is None
    assert body["error_code"] is None
    assert len(rig.transcriber.started) == 1


def test_a_sample_job_is_accepted() -> None:
    response = Rig().client.post(
        "/jobs", json={"sample_id": "invoice", "call_date": "2026-10-21", "speaker_names": ["Ana"]}
    )
    assert response.status_code == 202
    assert response.json()["status"] == "transcribing"


def test_a_text_job_is_accepted_and_dispatched() -> None:
    rig = Rig()

    response = rig.client.post("/jobs", json=TEXT_BODY)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "uploaded"
    assert rig.dispatcher.dispatched == [body["job_id"]]


def test_posting_the_same_audio_twice_returns_one_job() -> None:
    rig = Rig()
    rig.audio.put(KEY, make_wav(2.0))
    first = rig.client.post("/jobs", json=AUDIO_BODY).json()["job_id"]
    other_id = "c" * 32
    rig.audio.put(f"uploads/{other_id}.wav", make_wav(2.0))

    second = rig.client.post("/jobs", json=AUDIO_BODY | {"upload_id": other_id}).json()["job_id"]

    assert first == second


@pytest.mark.parametrize(
    "body",
    [
        {"call_date": "2026-10-21"},
        AUDIO_BODY | {"sample_id": "invoice"},
        AUDIO_BODY | {"transcript": TEXT_BODY["transcript"]},
        AUDIO_BODY | {"upload_id": "../../etc/passwd"},
        AUDIO_BODY | {"upload_id": "A" * 32},
        AUDIO_BODY | {"speaker_names": ["a", "b", "c"]},
        AUDIO_BODY | {"speaker_names": [""]},
        {k: v for k, v in AUDIO_BODY.items() if k != "call_date"},
        TEXT_BODY | {"speaker_names": ["Ana"]},
        TEXT_BODY | {"transcript": []},
        TEXT_BODY | {"transcript": [{"speaker": "A", "text": SECRET * 5_000}]},
        TEXT_BODY | {"surprise": SECRET},
    ],
    ids=[
        "no-source",
        "two-sources-audio",
        "two-sources-text",
        "path-traversal",
        "uppercase-id",
        "three-names",
        "blank-name",
        "no-date",
        "text-with-names",
        "empty-transcript",
        "huge-transcript",
        "unknown-field",
    ],
)
def test_invalid_job_requests_get_422_without_echoing_input(body: dict[str, Any]) -> None:
    response = Rig().client.post("/jobs", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert SECRET not in response.text


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        (AUDIO_BODY, 404, "upload_not_found"),
        ({"sample_id": "nope", "call_date": "2026-10-21"}, 404, "sample_not_found"),
    ],
)
def test_missing_inputs_are_404(body: dict[str, Any], status: int, code: str) -> None:
    response = Rig().client.post("/jobs", json=body)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(
    ("seconds", "code"), [(60.5, "audio_too_long"), (0.0, "audio_invalid")], ids=["long", "empty"]
)
def test_bad_audio_is_422_and_deleted(seconds: float, code: str) -> None:
    rig = Rig()
    rig.audio.put(KEY, make_wav(seconds))

    response = rig.client.post("/jobs", json=AUDIO_BODY)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert rig.audio.deleted == [KEY]


def test_without_a_job_service_the_routes_are_503() -> None:
    client = Rig(with_service=False).client
    for response in (
        client.post("/jobs", json=TEXT_BODY),
        client.get(f"/jobs/{'0' * 64}"),
        client.get("/samples"),
    ):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "jobs_unavailable"


def test_text_jobs_without_a_dispatcher_are_503() -> None:
    rig = Rig()
    service = JobService(
        rig.store, rig.audio, rig.transcriber, SampleCatalog([]), None, clock=lambda: NOW
    )
    extractor = Extractor(FakeAdapter(), load_prompt("v1"))
    client = TestClient(create_app(extractor=extractor, jobs=service))

    response = client.post("/jobs", json=TEXT_BODY)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "jobs_unavailable"


# --- GET /jobs/{id} ------------------------------------------------------------------------------


def test_a_finished_job_returns_transcript_analysis_and_latency() -> None:
    rig = Rig()
    rig.audio.put(KEY, make_wav(2.0), uploaded_at_ms=int(NOW * 1000) - 2_000)
    job_id = rig.client.post("/jobs", json=AUDIO_BODY).json()["job_id"]
    turns = [Turn(speaker="Ana", text="Hello.", start_ms=0, end_ms=400)]
    done = JobUpdate(
        status=JobStatus.DONE,
        turns=turns,
        analysis=analysis(),
        transcribed_at=int(NOW * 1000) + 15_000,
        analyzing_at=int(NOW * 1000) + 15_500,
        finished_at=int(NOW * 1000) + 17_000,
    )
    assert rig.store.transition(job_id, JobStatus.TRANSCRIBING, done)

    response = rig.client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["status"] == "done"
    assert body["transcript"] == [
        {"speaker": "Ana", "text": "Hello.", "start_ms": 0, "end_ms": 400}
    ]
    assert body["analysis"]["metadata"]["prompt_version"] == "v1"
    assert body["latency_ms"] == {
        "upload_ms": 2_000,
        "transcribe_ms": 15_000,
        "analyze_ms": 1_500,
        "total_ms": 17_000,
    }


def test_a_failed_job_reports_its_error_code() -> None:
    rig = Rig()
    rig.audio.put(KEY, make_wav(2.0))
    job_id = rig.client.post("/jobs", json=AUDIO_BODY).json()["job_id"]
    failed = JobUpdate(status=JobStatus.FAILED, error_code="transcription_failed")
    rig.store.transition(job_id, JobStatus.TRANSCRIBING, failed)

    body = rig.client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "failed"
    assert body["error_code"] == "transcription_failed"


def test_an_unknown_job_is_404() -> None:
    response = Rig().client.get(f"/jobs/{'0' * 64}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


@pytest.mark.parametrize("job_id", ["short", "Z" * 64, "0" * 65])
def test_a_malformed_job_id_is_422(job_id: str) -> None:
    response = Rig().client.get(f"/jobs/{job_id}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- GET /samples --------------------------------------------------------------------------------


def test_samples_lists_the_clips_without_their_hashes() -> None:
    response = Rig().client.get("/samples")
    assert response.status_code == 200
    assert response.json() == [
        {"id": "invoice", "title": "Resending an invoice", "duration_ms": 41_500}
    ]


# --- Logging -------------------------------------------------------------------------------------


def test_job_requests_log_no_transcript_text(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    with caplog.at_level(logging.DEBUG):
        job_id = rig.client.post("/jobs", json=TEXT_BODY).json()["job_id"]
        rig.client.get(f"/jobs/{job_id}")
        rig.client.post("/jobs", json=TEXT_BODY | {"call_date": "bad"})
    assert SECRET not in caplog.text
