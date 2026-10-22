"""The spend cap in use: what the service, worker and API record, and what they refuse."""

import asyncio
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from commitment_tracker.api.app import create_app
from commitment_tracker.extractor.errors import ModelUnavailable
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.pricing import cost_usd
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.guardrails.spend import MemorySpendStore, SpendCap, transcribe_cost_usd
from commitment_tracker.jobs.memory import MemoryJobStore
from commitment_tracker.jobs.samples import SampleCatalog, SampleClip
from commitment_tracker.jobs.service import JobService
from commitment_tracker.jobs.worker import JobWorker, TranscribeOutcome
from commitment_tracker.transcription.fake import FakeTranscriber
from commitment_tracker.transcription.protocol import AudioRef
from tests.fakes import DEFAULT_USAGE, FakeAdapter, FakeAudioStore, FakeDispatcher, reply
from tests.test_api import BODY, GOOD_OUTPUT
from tests.test_job_worker import JOB_ID, TIMED, make_job
from tests.wav import make_wav

NOON = 1_761_048_000.0  # 2025-10-21 12:00 UTC
DAY = "2025-10-21"
UPLOAD_ID = "a" * 32
KEY = f"uploads/{UPLOAD_ID}.wav"
SAMPLE = SampleClip(id="invoice", title="Invoice", duration_ms=40_000, sha256="b" * 64)
HAIKU = "claude-haiku-5-5"
MODEL_COST = cost_usd(HAIKU, DEFAULT_USAGE)
AUDIO_BODY: dict[str, Any] = {"upload_id": UPLOAD_ID, "call_date": "2026-10-21"}
TEXT_BODY: dict[str, Any] = {
    "transcript": [{"speaker": "A", "text": "Hello."}],
    "call_date": "2026-10-21",
}


def spent(store: MemorySpendStore) -> float:
    return store.total_micros(DAY) / 1_000_000


def new_cap(budget: float = 5.0) -> tuple[SpendCap, MemorySpendStore]:
    store = MemorySpendStore()
    return SpendCap(store, budget, clock=lambda: NOON), store


# --- JobService ----------------------------------------------------------------------------------


class ServiceRig:
    def __init__(self, budget: float = 5.0) -> None:
        self.spend, self.store = new_cap(budget)
        self.audio = FakeAudioStore()
        self.transcriber = FakeTranscriber()
        self.service = JobService(
            MemoryJobStore(clock=lambda: NOON),
            self.audio,
            self.transcriber,
            SampleCatalog([SAMPLE]),
            FakeDispatcher(),
            clock=lambda: NOON,
            spend=self.spend,
        )


def test_starting_an_upload_records_the_transcribe_estimate() -> None:
    rig = ServiceRig()
    rig.audio.put(KEY, make_wav(30.0))

    rig.service.start_upload(UPLOAD_ID, date(2026, 10, 21), [])

    assert spent(rig.store) == pytest.approx(transcribe_cost_usd(30_000))


def test_starting_a_sample_records_the_clips_duration() -> None:
    rig = ServiceRig()

    rig.service.start_sample("invoice", date(2026, 10, 21), [])

    assert spent(rig.store) == pytest.approx(transcribe_cost_usd(40_000))


def test_a_duplicate_job_costs_nothing_more() -> None:
    rig = ServiceRig()
    rig.service.start_sample("invoice", date(2026, 10, 21), [])
    before = spent(rig.store)

    rig.service.start_sample("invoice", date(2026, 10, 21), [])

    assert spent(rig.store) == before


def test_a_transcription_that_will_not_start_costs_nothing() -> None:
    rig = ServiceRig()

    class Broken(FakeTranscriber):
        def start(self, audio: AudioRef, job_id: str) -> None:
            raise RuntimeError("boom")

    rig.service = JobService(
        MemoryJobStore(clock=lambda: NOON),
        rig.audio,
        Broken(),
        SampleCatalog([SAMPLE]),
        None,
        clock=lambda: NOON,
        spend=rig.spend,
    )

    rig.service.start_sample("invoice", date(2026, 10, 21), [])

    assert spent(rig.store) == 0


# --- JobWorker -----------------------------------------------------------------------------------


class WorkerRig:
    def __init__(self, *replies: Any) -> None:
        self.spend, self.store = new_cap()
        self.jobs = MemoryJobStore(clock=lambda: NOON)
        self.jobs.create(make_job(expires_at=int(NOON) + 3600, created_at=int(NOON * 1000)))
        self.worker = JobWorker(
            self.jobs,
            FakeAudioStore(),
            FakeTranscriber({JOB_ID: TIMED}),
            Extractor(FakeAdapter(*replies), load_prompt("v1")),
            clock=lambda: NOON,
            spend=self.spend,
        )

    def run(self) -> None:
        asyncio.run(self.worker.on_transcribe(TranscribeOutcome(JOB_ID, completed=True)))


def test_the_worker_records_the_model_cost() -> None:
    rig = WorkerRig(reply(GOOD_OUTPUT, served_by=HAIKU))

    rig.run()

    assert MODEL_COST is not None
    assert spent(rig.store) == pytest.approx(MODEL_COST)


def test_a_model_with_no_price_adds_nothing() -> None:
    rig = WorkerRig(reply(GOOD_OUTPUT, served_by="unpriced-model"))

    rig.run()

    assert spent(rig.store) == 0


def test_a_failed_analysis_records_nothing() -> None:
    rig = WorkerRig(ModelUnavailable("down"))

    rig.run()

    assert spent(rig.store) == 0


# --- API -----------------------------------------------------------------------------------------


class ApiRig:
    def __init__(self, *replies: Any, budget: float = 5.0) -> None:
        self.spend, self.store = new_cap(budget)
        self.audio = FakeAudioStore()
        jobs = JobService(
            MemoryJobStore(clock=lambda: NOON),
            self.audio,
            FakeTranscriber(),
            SampleCatalog([SAMPLE]),
            FakeDispatcher(),
            clock=lambda: NOON,
            spend=self.spend,
        )
        extractor = Extractor(FakeAdapter(*replies, model=HAIKU), load_prompt("v1"))
        self.client = TestClient(create_app(extractor=extractor, jobs=jobs, spend=self.spend))


def test_analyze_records_what_the_model_cost() -> None:
    rig = ApiRig(reply(GOOD_OUTPUT, served_by=HAIKU))

    assert rig.client.post("/analyze", json=BODY).status_code == 200

    assert MODEL_COST is not None
    assert spent(rig.store) == pytest.approx(MODEL_COST)


@pytest.mark.parametrize(
    ("path", "body"),
    [("/analyze", BODY), ("/jobs", AUDIO_BODY), ("/jobs", TEXT_BODY)],
    ids=["analyze", "audio-job", "text-job"],
)
def test_new_work_is_refused_once_the_budget_is_used(path: str, body: dict[str, Any]) -> None:
    rig = ApiRig(budget=1.0)
    rig.spend.record(1.0)
    rig.audio.put(KEY, make_wav(2.0))

    response = rig.client.post(path, json=body)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "daily_budget_exhausted"
    assert response.headers["retry-after"] == str(12 * 3600)


def test_reading_and_uploading_still_work_when_the_budget_is_used() -> None:
    rig = ApiRig(budget=1.0)
    rig.spend.record(1.0)

    assert rig.client.get("/health").status_code == 200
    assert rig.client.get("/samples").status_code == 200
    assert rig.client.get(f"/jobs/{'0' * 64}").status_code == 404


def test_a_refused_request_is_refused_before_its_body_is_checked() -> None:
    rig = ApiRig(budget=1.0)
    rig.spend.record(1.0)

    assert rig.client.post("/jobs", json={}).status_code == 503


def test_the_job_that_crosses_the_budget_still_runs_and_the_next_is_refused() -> None:
    rig = ApiRig(budget=0.01)
    rig.audio.put(KEY, make_wav(30.0))  # about $0.012

    assert rig.client.post("/jobs", json=AUDIO_BODY).status_code == 202
    assert rig.client.post("/jobs", json=TEXT_BODY).status_code == 503


def test_without_a_cap_nothing_is_refused() -> None:
    extractor = Extractor(FakeAdapter(), load_prompt("v1"))
    client = TestClient(create_app(extractor=extractor))
    assert client.get("/health").status_code == 200
