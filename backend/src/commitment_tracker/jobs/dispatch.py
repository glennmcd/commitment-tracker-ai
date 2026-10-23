"""Handing a text job to the worker Lambda with an asynchronous invoke."""

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types_boto3_lambda import LambdaClient

logger = logging.getLogger(__name__)

ANALYZE_TEXT = "analyze_text"


class LambdaWorkerDispatcher:
    def __init__(self, client: "LambdaClient", function_name: str) -> None:
        self._client = client
        self._function_name = function_name

    def dispatch(self, job_id: str) -> None:
        payload = json.dumps({"action": ANALYZE_TEXT, "job_id": job_id}, separators=(",", ":"))
        response = self._client.invoke(
            FunctionName=self._function_name,
            InvocationType="Event",
            Payload=payload.encode(),
        )
        if response["StatusCode"] != 202:
            raise RuntimeError(f"worker invoke returned {response['StatusCode']}, expected 202")
        logger.info("worker invoked job_id=%s", job_id)
