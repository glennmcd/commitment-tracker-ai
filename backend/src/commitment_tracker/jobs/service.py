"""Starting jobs: from an upload, a sample clip or text, with deduplication.

A job id is the SHA-256 of the audio (or the turns), the call date and the speaker names, so a
retried submission finds the job it already made. An upload is read once, checked as a WAV, hashed
and either becomes a job (Transcribe starts) or, if the job exists, is deleted as a duplicate.
Text jobs are stored and handed to the worker; the worker, not this module, analyses them.
Nothing here logs transcript text.
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable, Sequence
from datetime import date
from typing import Protocol

from commitment_tracker.guardrails.spend import SpendCap, transcribe_cost_usd
from commitment_tracker.jobs.audio import AudioInvalid, AudioTooLong, validate_wav
from commitment_tracker.jobs.audio_store import AudioStore
from commitment_tracker.jobs.record import (
    JOB_TTL_SECONDS,
    JobRecord,
    JobSource,
    JobStatus,
    JobUpdate,
)
from commitment_tracker.jobs.samples import SampleCatalog
from commitment_tracker.jobs.store import JobStore
from commitment_tracker.jobs.uploads import UPLOAD_PREFIX
from commitment_tracker.schemas import Turn
from commitment_tracker.transcription.protocol import AudioRef, Transcriber

logger = logging.getLogger(__name__)

TRANSCRIPTION_FAILED = "transcription_failed"
JOB_START_FAILED = "job_start_failed"


class JobsUnavailable(Exception):
    """Job storage is not configured."""


class TextJobsUnavailable(JobsUnavailable):
    """Text jobs need a worker to hand them to."""


class UploadNotFound(LookupError):
    pass


class SampleNotFound(LookupError):
    pass


class WorkerDispatcher(Protocol):
    def dispatch(self, job_id: str) -> None:
        """Hand a stored text job to the worker, without waiting for it."""
        ...


def _digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def job_id_for(audio_sha256: str, call_date: date, speaker_names: Sequence[str]) -> str:
    return _digest("audio", audio_sha256, call_date.isoformat(), list(speaker_names))


def text_job_id_for(turns: Sequence[Turn], call_date: date) -> str:
    return _digest("text", [[turn.speaker, turn.text] for turn in turns], call_date.isoformat())


class JobService:
    def __init__(
        self,
        store: JobStore,
        audio: AudioStore,
        transcriber: Transcriber,
        samples: SampleCatalog,
        dispatcher: WorkerDispatcher | None,
        *,
        clock: Callable[[], float] = time.time,
        spend: SpendCap | None = None,
    ) -> None:
        self._spend = spend
        self._store = store
        self._audio = audio
        self._transcriber = transcriber
        self._samples = samples
        self._dispatcher = dispatcher
        self._clock = clock

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _record(
        self, job_id: str, source: JobSource, call_date: date, **fields: object
    ) -> JobRecord:
        return JobRecord.model_validate(
            {
                "id": job_id,
                "source": source,
                "call_date": call_date,
                "created_at": self._now_ms(),
                "expires_at": int(self._clock()) + JOB_TTL_SECONDS,
                **fields,
            }
        )

    def get(self, job_id: str) -> JobRecord | None:
        return self._store.get(job_id)

    def samples(self) -> SampleCatalog:
        return self._samples

    # --- Audio -----------------------------------------------------------------------------------

    def start_upload(
        self, upload_id: str, call_date: date, speaker_names: Sequence[str]
    ) -> JobRecord:
        key = f"{UPLOAD_PREFIX}/{upload_id}.wav"
        try:
            stored = self._audio.read(key)
            if stored is None:
                raise UploadNotFound(upload_id)
            info = validate_wav(stored.data)
        except (AudioInvalid, AudioTooLong):
            self._audio.delete(key)
            raise
        job_id = job_id_for(hashlib.sha256(stored.data).hexdigest(), call_date, speaker_names)
        job = self._record(
            job_id,
            JobSource.UPLOAD,
            call_date,
            status=JobStatus.TRANSCRIBING,
            audio_key=key,
            speaker_names=list(speaker_names),
            upload_started_at=stored.uploaded_at_ms,
            transcribing_at=self._now_ms(),
        )
        result = self._start_audio_job(job, info.duration_ms)
        if result.audio_key != key:
            self._audio.delete(key)  # the same audio was uploaded before
        elif result.status is JobStatus.FAILED:
            self._audio.delete(key)
        return result

    def start_sample(
        self, sample_id: str, call_date: date, speaker_names: Sequence[str]
    ) -> JobRecord:
        clip = self._samples.get(sample_id)
        if clip is None:
            raise SampleNotFound(sample_id)
        job = self._record(
            job_id_for(clip.sha256, call_date, speaker_names),
            JobSource.SAMPLE,
            call_date,
            status=JobStatus.TRANSCRIBING,
            audio_key=clip.key,
            speaker_names=list(speaker_names),
            transcribing_at=self._now_ms(),
        )
        return self._start_audio_job(job, clip.duration_ms)

    def _start_audio_job(self, job: JobRecord, duration_ms: int) -> JobRecord:
        assert job.audio_key is not None
        stored = self._store.create(job)
        if stored is not job:
            logger.info("job deduplicated job_id=%s", job.id)
            return stored
        try:
            self._transcriber.start(AudioRef(self._audio.bucket, job.audio_key), job.id)
        except Exception as error:
            logger.warning(
                "transcription not started job_id=%s error=%s", job.id, type(error).__name__
            )
            return self._fail(job, JobStatus.TRANSCRIBING, TRANSCRIPTION_FAILED)
        if self._spend is not None:
            self._spend.record(transcribe_cost_usd(duration_ms))
        logger.info("job started job_id=%s source=%s", job.id, job.source.value)
        return job

    # --- Text ------------------------------------------------------------------------------------

    def start_text(self, turns: Sequence[Turn], call_date: date) -> JobRecord:
        if self._dispatcher is None:
            raise TextJobsUnavailable("no worker to hand text jobs to")
        job = self._record(
            text_job_id_for(turns, call_date),
            JobSource.TRANSCRIPT,
            call_date,
            status=JobStatus.UPLOADED,
            turns=list(turns),
        )
        stored = self._store.create(job)
        if stored is not job:
            logger.info("job deduplicated job_id=%s", job.id)
            return stored
        try:
            self._dispatcher.dispatch(job.id)
        except Exception as error:
            logger.warning("worker not invoked job_id=%s error=%s", job.id, type(error).__name__)
            return self._fail(job, JobStatus.UPLOADED, JOB_START_FAILED)
        logger.info("job started job_id=%s source=%s", job.id, job.source.value)
        return job

    # --- Failure ---------------------------------------------------------------------------------

    def _fail(self, job: JobRecord, expected: JobStatus, error_code: str) -> JobRecord:
        update = JobUpdate(
            status=JobStatus.FAILED, error_code=error_code, finished_at=self._now_ms()
        )
        return self._store.transition(job.id, expected, update) or self._store.get(job.id) or job
