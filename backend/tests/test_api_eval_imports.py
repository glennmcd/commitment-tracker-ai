"""POST /eval-imports, POST /eval-imports/check through the TestClient, on fakes."""

import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from commitment_tracker.api.app import ImportRequest, create_app
from commitment_tracker.evaluation.importer import ImportReport
from commitment_tracker.evaluation.sets import STAGING, load_set
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.jobs.memory import MemoryJobStore

# from commitment_tracker.jobs.record import JobStatus, JobUpdate
from commitment_tracker.jobs.samples import SampleCatalog, SampleClip
from commitment_tracker.jobs.service import JobService
from commitment_tracker.settings import Settings
from commitment_tracker.transcription.fake import FakeTranscriber
from tests.fakes import FakeAdapter, FakeAudioStore, FakeDispatcher

from .eval.conftest import TODAY, draft, root, standard_options, write_source  # ruff: ignore[F401]

NOW = 1_761_000_000.0
SAMPLE = SampleClip(id="invoice", title="Resending an invoice", duration_ms=41_500, sha256="b" * 64)


class Rig:
    def __init__(
        self,
        *,
        with_service: bool = True,
        eval_imports_enabled: bool = True,
        sets_dir: Path | None = None,
    ) -> None:
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
            create_app(
                extractor=extractor,
                jobs=service if with_service else None,
                settings=active_settings,
                sets_dir=sets_dir,
            )
        )


def test_eval_imports_check_disabled() -> None:
    request: ImportRequest = ImportRequest(
        source="testing_framework",
        content="dummy",
        batch="d1",
        provenance="test",
        generation_prompt="",
        today=TODAY.isoformat(),
    )
    rig = Rig(eval_imports_enabled=False)
    result = rig.client.post("/eval-imports/check", json=request.model_dump())
    assert result.status_code == 404


def test_eval_imports_check_enabled(tmp_path: Path, root: Path) -> None:  # ruff: ignore[F811]
    source_data = write_source(tmp_path, "```jsonl", "", json.dumps(draft("gem01-01")), "```")
    content_data = source_data.read_text(encoding="utf-8")
    ov = {"generation_prompt": "prompt-v1"}
    options = standard_options(root, **ov)
    request: ImportRequest = ImportRequest(
        source=str(source_data),
        content=content_data,
        batch=options["batch"],
        provenance=options["provenance"],
        generation_prompt=options["generation_prompt"],
        today=TODAY.isoformat(),
    )
    sets_dir = options["root"]
    directory = root / STAGING / options["batch"]
    rig = Rig(eval_imports_enabled=True, sets_dir=sets_dir)
    result = rig.client.post("/eval-imports/check", json=request.model_dump())
    assert result.status_code == 200
    assert not directory.exists()


def test_eval_imports_batch_disabled() -> None:
    request: ImportRequest = ImportRequest(
        source="testing_framework",
        content="dummy",
        batch="d1",
        provenance="test",
        generation_prompt="",
        today=TODAY.isoformat(),
    )
    rig = Rig(eval_imports_enabled=False)
    result = rig.client.post("/eval-imports", json=request.model_dump())
    assert result.status_code == 404


def test_eval_imports_import_enabled(tmp_path: Path, root: Path) -> None:  # ruff: ignore[F811]
    source_data = write_source(
        tmp_path,
        json.dumps(draft("gem01-01")),
        json.dumps(
            draft(
                "gem01-02",
                "We'll ship the build by end of next week.",
                expected=[
                    {
                        **draft("x")["expected"][0],
                        "quote": "We'll ship the build by end of next week.",
                        "action_keywords": ["ship"],
                        "due_raw": "by end of next week",
                        "due_resolved": "2026-10-30",
                    }
                ],
            )
        ),
    )
    content_data = source_data.read_text(encoding="utf-8")
    ov = {"generation_prompt": "prompt-v1"}
    options = standard_options(root, **ov)
    request: ImportRequest = ImportRequest(
        source=str(source_data),
        content=content_data,
        batch=options["batch"],
        provenance=options["provenance"],
        generation_prompt=options["generation_prompt"],
        today=TODAY.isoformat(),
    )
    sets_dir = options["root"]
    directory = root / STAGING / options["batch"]
    rig = Rig(eval_imports_enabled=True, sets_dir=sets_dir)
    result = rig.client.post("/eval-imports", json=request.model_dump())
    ir: ImportReport = ImportReport(**result.json())

    assert result.status_code == 201
    assert directory.exists()
    assert ir.imported == 2
    assert ir.rejections == []
    staged = load_set("staging/gem01", root)
    assert {item.review for item in staged.items} == {"unreviewed"}
    assert {item.provenance for item in staged.items} == {"gemini-3-pro"}
    (source_entry,) = staged.manifest.sources
    assert source_entry.batch == "gem01"
    assert source_entry.generation_prompt == "prompt-v1"
    assert source_entry.imported == TODAY
    assert source_entry.call_date == date(2026, 10, 21)
    assert source_entry.items == 2
    report = json.loads((root / "staging" / "gem01" / "import.json").read_text("utf-8"))
    assert report["imported"] == 2


def test_eval_imports_bad_batch_name(tmp_path: Path, root: Path) -> None:  # ruff: ignore[F811]
    source_data = write_source(tmp_path, "```jsonl", "", json.dumps(draft("gem01-01")), "```")
    content_data = source_data.read_text(encoding="utf-8")
    ov = {"generation_prompt": "prompt-v1", "batch": "bad#batch"}
    options = standard_options(root, **ov)
    request: ImportRequest = ImportRequest(
        source=str(source_data),
        content=content_data,
        batch=options["batch"],
        provenance=options["provenance"],
        generation_prompt=options["generation_prompt"],
        today=TODAY.isoformat(),
    )
    sets_dir = options["root"]
    rig = Rig(eval_imports_enabled=True, sets_dir=sets_dir)
    result = rig.client.post("/eval-imports", json=request.model_dump())
    assert result.status_code == 422


def test_eval_imports_batch_exists(tmp_path: Path, root: Path) -> None:  # ruff: ignore[F811]
    source_data = write_source(tmp_path, "```jsonl", "", json.dumps(draft("gem01-01")), "```")
    content_data = source_data.read_text(encoding="utf-8")
    ov = {"generation_prompt": "prompt-v1"}
    options = standard_options(root, **ov)
    request: ImportRequest = ImportRequest(
        source=str(source_data),
        content=content_data,
        batch=options["batch"],
        provenance=options["provenance"],
        generation_prompt=options["generation_prompt"],
        today=TODAY.isoformat(),
    )
    sets_dir = options["root"]
    rig = Rig(eval_imports_enabled=True, sets_dir=sets_dir)
    # First import should succeed
    result = rig.client.post("/eval-imports", json=request.model_dump())
    assert result.status_code == 201
    # Second import with the same batch should fail
    result = rig.client.post("/eval-imports", json=request.model_dump())
    assert result.status_code == 409


def test_eval_imports_nothing_valid(tmp_path: Path, root: Path) -> None:  # ruff: ignore[F811]
    source_data = write_source(tmp_path, "```jsonl", "", "invalid json", "```")
    content_data = source_data.read_text(encoding="utf-8")
    ov = {"generation_prompt": "prompt-v1"}
    options = standard_options(root, **ov)
    request: ImportRequest = ImportRequest(
        source=str(source_data),
        content=content_data,
        batch=options["batch"],
        provenance=options["provenance"],
        generation_prompt=options["generation_prompt"],
        today=TODAY.isoformat(),
    )
    sets_dir = options["root"]
    directory = root / STAGING / options["batch"]
    rig = Rig(eval_imports_enabled=True, sets_dir=sets_dir)
    result = rig.client.post("/eval-imports/check", json=request.model_dump())
    ir: ImportReport = ImportReport(**result.json())
    assert result.status_code == 200
    assert ir.imported == 0

    result = rig.client.post("/eval-imports", json=request.model_dump())
    assert result.status_code == 422
    # assert "nothing_to_import" in result.text
    assert not directory.exists()
