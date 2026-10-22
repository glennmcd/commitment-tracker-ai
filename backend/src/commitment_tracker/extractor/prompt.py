"""Versioned prompts and the user message built from an analysis request.

A prompt version is a file `prompts/<version>.md`; changing the prompt means adding a version, so
evaluation reports can name the prompt they ran. The transcript goes into the user message, after
the cached system prompt.
"""

import hashlib
import html
import re
from dataclasses import dataclass
from importlib.resources import files

from commitment_tracker.schemas import AnalyzeRequest

VERSION = re.compile(r"v[0-9]+")
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# Our own tags inside turn text are neutralised so a turn can't close the transcript early.
OUR_TAGS = re.compile(r"<(/?)(turn|transcript|call_date|timezone)\b", re.IGNORECASE)


class UnknownPromptVersion(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    sha256: str


def load_prompt(version: str) -> Prompt:
    if not VERSION.fullmatch(version):
        raise UnknownPromptVersion(f"prompt version must look like v1, not {version!r}")
    resource = files("commitment_tracker.extractor").joinpath("prompts", f"{version}.md")
    if not resource.is_file():
        raise UnknownPromptVersion(f"no prompt file for version {version}")
    system = resource.read_text(encoding="utf-8")
    return Prompt(version, system, hashlib.sha256(system.encode("utf-8")).hexdigest())


def build_user_message(request: AnalyzeRequest) -> str:
    """Call date and transcript as tagged data. Turn text stays verbatim so quotes can match it."""
    day = request.call_date
    lines = [f"<call_date>{day.isoformat()} ({DAY_NAMES[day.weekday()]})</call_date>"]
    if request.timezone:
        lines.append(f"<timezone>{html.escape(request.timezone)}</timezone>")
    lines.append("<transcript>")
    for index, turn in enumerate(request.transcript):
        speaker = html.escape(turn.speaker, quote=True)
        text = OUR_TAGS.sub(r"&lt;\1\2", turn.text)
        lines.append(f'<turn index="{index}" speaker="{speaker}">{text}</turn>')
    lines.append("</transcript>")
    return "\n".join(lines)
