"""The job worker: what happens after a Transcribe job finishes, and for text jobs.

For audio, the `Transcribe Job State Change` event (ADR 0002) moves a job from `transcribing` to
`analyzing`: the worker reads the output, names the speakers, claims the job with a conditional
update, deletes the audio, the output and the Transcribe job, then runs the extractor. Text jobs
start in `uploaded` and skip the first half. The claim makes redelivery harmless: an event for a
job that is not waiting is ignored. Cleanup errors are logged and never fail a job (the bucket's
lifecycle rule backs them up); a sample clip is never deleted. Nothing here logs transcript text.
"""

import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from commitment_tracker.extractor.errors import ExtractionError
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.guardrails.spend import SpendCap
from commitment_tracker.jobs.audio_store import AudioStore
from commitment_tracker.jobs.record import JobRecord, JobSource, JobStatus, JobUpdate
from commitment_tracker.jobs.service import TRANSCRIPTION_FAILED
from commitment_tracker.jobs.store import JobStore
from commitment_tracker.schemas import AnalyzeRequest, Turn
from commitment_tracker.transcription.protocol import Transcriber
from commitment_tracker.transcription.turns import TranscriptFormatError, name_turns

logger = logging.getLogger(__name__)

NO_SPEECH = "no_speech"
ANALYSIS_FAILED = "analysis_failed"
_JOB_NAME = re.compile(r"^ct-([0-9a-f]{64})$")


@dataclass(frozen=True)
class TranscribeOutcome:
    job_id: str
    completed: bool  # False when Transcribe reported the job failed


def parse_transcribe_event(event: Mapping[str, Any]) -> TranscribeOutcome | None:
    """The outcome in an EventBridge `Transcribe Job State Change` event, or None for anything
    else (another job name, a status that isn't final, a malformed event)."""
    detail = event.get("detail")
    if not isinstance(detail, Mapping):
        return None
    match = _JOB_NAME.match(str(detail.get("TranscriptionJobName", "")))
    status = detail.get("TranscriptionJobStatus")
    if match is None or status not in ("COMPLETED", "FAILED"):
        return None
    return TranscribeOutcome(job_id=match.group(1), completed=status == "COMPLETED")


class JobWorker:
    def __init__(
        self,
        store: JobStore,
        audio: AudioStore,
        transcriber: Transcriber,
        extractor: Extractor,
        *,
        clock: Callable[[], float] = time.time,
        spend: SpendCap | None = None,
    ) -> None:
        self._spend = spend
        self._store = store
        self._audio = audio
        self._transcriber = transcriber
        self._extractor = extractor
        self._clock = clock

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    # --- Audio jobs ------------------------------------------------------------------------------

    async def on_transcribe(self, outcome: TranscribeOutcome) -> None:
        arrived_at = self._now_ms()
        job = self._store.get(outcome.job_id)
        if job is None or job.status is not JobStatus.TRANSCRIBING:
            logger.info("transcribe event ignored job_id=%s", outcome.job_id)
            return
        if not outcome.completed:
            self._fail_and_clean(job, TRANSCRIPTION_FAILED)
            return
        try:
            timed = self._transcriber.result(job.id)
        except (LookupError, TranscriptFormatError) as error:
            logger.warning("transcript unreadable job_id=%s error=%s", job.id, type(error).__name__)
            self._fail_and_clean(job, TRANSCRIPTION_FAILED)
            return
        if not timed:
            self._fail_and_clean(job, NO_SPEECH)
            return
        turns = name_turns(timed, job.speaker_names)
        claimed = self._store.transition(
            job.id,
            JobStatus.TRANSCRIBING,
            JobUpdate(
                status=JobStatus.ANALYZING,
                turns=turns,
                transcribed_at=arrived_at,
                analyzing_at=self._now_ms(),
            ),
        )
        if claimed is None:
            logger.info("transcribe event lost the claim job_id=%s", job.id)
            return
        self._clean_up(claimed)
        await self._analyze(claimed, turns)

    # --- Text jobs -------------------------------------------------------------------------------

    async def on_text_job(self, job_id: str) -> None:
        job = self._store.get(job_id)
        if job is None or job.source is not JobSource.TRANSCRIPT or job.turns is None:
            logger.info("text job ignored job_id=%s", job_id)
            return
        claimed = self._store.transition(
            job.id,
            JobStatus.UPLOADED,
            JobUpdate(status=JobStatus.ANALYZING, analyzing_at=self._now_ms()),
        )
        if claimed is None:
            logger.info("text job already claimed job_id=%s", job_id)
            return
        await self._analyze(claimed, job.turns)

    # --- Shared ----------------------------------------------------------------------------------

    async def _analyze(self, job: JobRecord, turns: list[Turn]) -> None:
        try:
            request = AnalyzeRequest(transcript=turns, call_date=job.call_date)
            result = await self._extractor.analyze(request)
        except ExtractionError as error:
            self._finish(job, JobUpdate(status=JobStatus.FAILED, error_code=error.code))
            return
        except Exception as error:  # a job must always finish, whatever went wrong
            logger.warning("analysis failed job_id=%s error=%s", job.id, type(error).__name__)
            self._finish(job, JobUpdate(status=JobStatus.FAILED, error_code=ANALYSIS_FAILED))
            return
        if self._spend is not None and result.metadata.cost_usd is not None:
            self._spend.record(result.metadata.cost_usd)
        self._finish(job, JobUpdate(status=JobStatus.DONE, analysis=result))
        logger.info(
            "job done job_id=%s spans=%d latency_ms=%d",
            job.id,
            len(result.spans),
            result.metadata.latency_ms,
        )

    def _finish(self, job: JobRecord, update: JobUpdate) -> None:
        done = update.model_copy(update={"finished_at": self._now_ms()})
        if self._store.transition(job.id, JobStatus.ANALYZING, done) is None:
            logger.warning("job changed while analysing job_id=%s", job.id)

    def _fail_and_clean(self, job: JobRecord, error_code: str) -> None:
        update = JobUpdate(
            status=JobStatus.FAILED, error_code=error_code, finished_at=self._now_ms()
        )
        if self._store.transition(job.id, JobStatus.TRANSCRIBING, update) is None:
            return  # another delivery got there first, and it cleans up
        logger.info("job failed job_id=%s code=%s", job.id, error_code)
        self._clean_up(job)

    def _clean_up(self, job: JobRecord) -> None:
        """Delete the Transcribe output and job, and the audio unless it is a sample clip."""
        try:
            self._transcriber.delete(job.id)
        except Exception as error:
            logger.warning(
                "transcribe cleanup failed job_id=%s error=%s", job.id, type(error).__name__
            )
        if job.source is JobSource.UPLOAD and job.audio_key is not None:
            try:
                self._audio.delete(job.audio_key)
            except Exception as error:
                logger.warning(
                    "audio cleanup failed job_id=%s error=%s", job.id, type(error).__name__
                )
