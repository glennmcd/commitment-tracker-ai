"""CloudWatch metrics through the embedded metric format (EMF): one JSON line on stdout per data
point, which Lambda ships to the log group and CloudWatch turns into a metric. No API call, no extra
permission. The lines go through a logger of their own that does not propagate, so they never reach
the application log and carry no prefix. Until `enable_emf_output` is called (the Lambda handlers do
it) the lines are dropped, which keeps tests and local runs quiet.
"""

import json
import logging
import math
import sys
import time
from typing import TextIO

NAMESPACE = "CommitmentTracker"
SPEND_FRACTION = "DailySpendFraction"

_logger = logging.getLogger("commitment_tracker.metrics")
_logger.propagate = False
_logger.setLevel(logging.INFO)
_handler: logging.Handler | None = None


def enable_emf_output(stream: TextIO | None = None) -> None:
    """Write metric lines to `stream` (stdout by default). Calling it again replaces the stream."""
    global _handler
    disable_emf_output()
    _handler = logging.StreamHandler(stream or sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)


def disable_emf_output() -> None:
    global _handler
    if _handler is not None:
        _logger.removeHandler(_handler)
        _handler = None


def emf_output_enabled() -> bool:
    return _handler is not None


def spend_fraction_line(fraction: float, *, now: float | None = None) -> str:
    """The EMF record for the day's spending as a fraction of the daily budget (1.0 is the cap)."""
    if not math.isfinite(fraction) or fraction < 0:
        raise ValueError("fraction must be a finite, non-negative number")
    moment = time.time() if now is None else now
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(moment * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": NAMESPACE,
                        "Dimensions": [[]],
                        "Metrics": [{"Name": SPEND_FRACTION, "Unit": "None"}],
                    }
                ],
            },
            SPEND_FRACTION: fraction,
        },
        separators=(",", ":"),
    )


def emit_spend_fraction(fraction: float) -> None:
    _logger.info(spend_fraction_line(fraction))
