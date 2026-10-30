"""POST /eval-imports, POST /eval-imports/check through the TestClient, on fakes."""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from commitment_tracker.api.app import ImportRequest, create_app
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.jobs.memory import MemoryJobStore
# from commitment_tracker.jobs.record import JobStatus, JobUpdate
from commitment_tracker.jobs.samples import SampleCatalog, SampleClip
from commitment_tracker.jobs.service import JobService
from commitment_tracker.schemas import Turn
from commitment_tracker.transcription.fake import FakeTranscriber

from commitment_tracker.settings import Settings
# from backend.tests.eval.builders import response
from tests.fakes import FakeAdapter, FakeAudioStore, FakeDispatcher
# from tests.test_jobs import analysis
# from tests.wav import make_wav

NOW = 1_761_000_000.0
SAMPLE = SampleClip(id="invoice", title="Resending an invoice", duration_ms=41_500, sha256="b" * 64)

class Rig:
    def __init__(self, *, with_service: bool = True, eval_imports_enabled: bool = True) -> None:
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
        active_settings = Settings()
        active_settings.eval_imports_enabled = eval_imports_enabled
        self.client = TestClient(
            create_app(extractor=extractor, jobs=service if with_service else None, settings=active_settings)
        )



def test_eval_imports_check_disabled() -> None:
  
  request:ImportRequest = ImportRequest(source="test", content="dummy", batch="d1", provenance="test", generation_prompt="") 
  
  rig = Rig(eval_imports_enabled=False)
  result = rig.client.post("/eval-imports/check", json=request.model_dump())               
  assert result.status_code == 404
