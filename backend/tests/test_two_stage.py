"""The two-stage extractor: a cheap screen, then the strong model on flagged turns with context."""

import asyncio
import json
import re
from collections.abc import Callable
from datetime import date

import pytest

from commitment_tracker.extractor.adapter import ModelReply, ModelRequest
from commitment_tracker.extractor.errors import ModelUnavailable
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.factory import build_analyzer
from commitment_tracker.extractor.model_output import ModelDue, ModelOutput, ModelSpan
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.extractor.two_stage import NON_NONE, TwoStageExtractor
from commitment_tracker.schemas import (
    LEDGER_LABELS,
    AnalyzeRequest,
    AnalyzeResponse,
    Label,
    Precision,
    Span,
    Turn,
)
from commitment_tracker.settings import Settings
from tests.fakes import FakeAdapter, FunctionAdapter, reply

TURN = re.compile(r'<turn index="(\d+)" speaker="[^"]*">(.*?)</turn>')


def labeller(
    rules: dict[str, Label], *, served_by: str = "fake-model"
) -> Callable[[ModelRequest], ModelReply]:
    """Answers with one span per turn: the label of the first rule whose word is in the turn."""

    def answer(request: ModelRequest) -> ModelReply:
        spans = []
        for index, text in TURN.findall(str(request.messages[0].content)):
            label = next((lab for word, lab in rules.items() if word in text), Label.NONE)
            ledger = label in LEDGER_LABELS
            spans.append(
                {
                    "turn_index": int(index),
                    "label": label.value,
                    "owner": "seller" if ledger else None,
                    "recipient": None,
                    "action": "send it" if ledger else None,
                    "due": {"raw": None, "precision_hint": "none"},
                    "condition": "approved" if label is Label.CONDITIONAL else None,
                    "confidence": 0.9,
                    "quote": text,
                    "rationale": "test",
                    "ambiguous": False,
                }
            )
        text = json.dumps({"spans": spans})
        return reply(text, served_by=served_by)

    return answer


def turns(*texts: str) -> AnalyzeRequest:
    return AnalyzeRequest(
        transcript=[Turn(speaker=f"s{i % 2}", text=t) for i, t in enumerate(texts)],
        call_date=date(2026, 10, 21),
    )


def pipeline(
    screen_rules: dict[str, Label],
    extract_rules: dict[str, Label],
    *,
    flag_labels: frozenset[Label] = NON_NONE,
    extract_answer: Callable[[ModelRequest], ModelReply | Exception] | None = None,
) -> tuple[TwoStageExtractor, FunctionAdapter, FunctionAdapter]:
    prompt = load_prompt("v1")
    screen = FunctionAdapter(
        labeller(screen_rules, served_by="claude-haiku-5-5"), model="claude-haiku-5-5"
    )
    extract = FunctionAdapter(
        extract_answer or labeller(extract_rules, served_by="claude-opus-5-5"),
        model="claude-opus-5-5",
    )
    two = TwoStageExtractor(
        Extractor(screen, prompt), Extractor(extract, prompt), flag_labels=flag_labels
    )
    return two, screen, extract


def sent_turns(request: ModelRequest) -> list[str]:
    return [text for _, text in TURN.findall(str(request.messages[0].content))]


TEXTS = (
    "Hi there.",  # 0
    "How was the trip?",  # 1
    "Fine, thanks.",  # 2
    "I'll send the pricing.",  # 3  flagged
    "Great.",  # 4
    "Anything else?",  # 5
    "Weather is nice.",  # 6
    "We should meet again.",  # 7  flagged
)


def test_flagged_turns_go_to_the_extract_model_with_two_turns_of_context() -> None:
    seen: list[list[str]] = []
    base = labeller({"send": Label.COMMITMENT, "should": Label.SUGGESTION})

    def record(request: ModelRequest) -> ModelReply:
        seen.append(sent_turns(request))
        return base(request)

    two, screen, extract = pipeline(
        {"send": Label.COMMITMENT, "should": Label.SUGGESTION}, {}, extract_answer=record
    )
    result = asyncio.run(two.analyze_detailed(turns(*TEXTS)))
    assert result.flagged_turns == [3, 7]
    assert result.windows == [(1, 3), (5, 7)]
    assert seen == [list(TEXTS[1:4]), list(TEXTS[5:8])]
    assert (screen.calls, extract.calls) == (1, 2)


def test_overlapping_windows_merge() -> None:
    two, _, extract = pipeline({"send": Label.COMMITMENT}, {"send": Label.COMMITMENT})
    texts = ("Hello.", "I'll send A.", "Ok.", "I'll send B.", "Bye.")
    result = asyncio.run(two.analyze_detailed(turns(*texts)))
    assert result.windows == [(0, 3)]
    assert extract.calls == 1


def test_extract_labels_replace_the_screen_on_flagged_turns_only() -> None:
    # The screen calls turn 3 a COMMITMENT; the extract model says HEDGED. It also labels the
    # context turn 2 a REQUEST, which must be discarded: context turns are not re-judged.
    two, _, _ = pipeline(
        {"send": Label.COMMITMENT, "should": Label.SUGGESTION},
        {"send": Label.HEDGED, "Fine": Label.REQUEST, "should": Label.SUGGESTION},
    )
    response = asyncio.run(two.analyze(turns(*TEXTS)))
    labels = {span.turn_index: span.label for span in response.spans}
    assert labels[3] is Label.HEDGED
    assert labels[2] is Label.NONE  # the screen's label stands on an unflagged turn
    assert labels[7] is Label.SUGGESTION
    assert [span.turn_index for span in response.spans] == list(range(len(TEXTS)))
    assert response.spans[3].quote == TEXTS[3]  # remapped back to the original turn


def test_nothing_flagged_never_calls_the_extract_model() -> None:
    two, screen, extract = pipeline({}, {})
    result = asyncio.run(two.analyze_detailed(turns("Hi.", "Nice weather.")))
    assert (screen.calls, extract.calls) == (1, 0)
    assert result.flagged_turns == []
    metadata = result.response.metadata
    assert (metadata.model, metadata.served_by) == ("two-stage", "claude-haiku-5-5")
    assert [stage.stage for stage in result.stages] == ["screen"]


def test_metadata_sums_both_stages() -> None:
    two, _, _ = pipeline({"send": Label.COMMITMENT}, {"send": Label.COMMITMENT})
    result = asyncio.run(two.analyze_detailed(turns("Hi.", "I'll send it.")))
    metadata = result.response.metadata
    assert metadata.model == "two-stage"
    assert metadata.input_tokens == sum(stage.input_tokens for stage in result.stages)
    assert metadata.output_tokens == 2 * 400
    assert metadata.served_by == "claude-opus-5-5"
    costs = [s.cost_usd for s in result.stages]
    assert None not in costs
    assert metadata.cost_usd == pytest.approx(sum(c for c in costs if c is not None))
    assert [stage.stage for stage in result.stages] == ["screen", "extract"]


def test_a_stricter_flag_rule_skips_non_ledger_turns() -> None:
    two, _, extract = pipeline(
        {"should": Label.SUGGESTION}, {}, flag_labels=frozenset(LEDGER_LABELS)
    )
    result = asyncio.run(two.analyze_detailed(turns("We should meet.", "Sure.")))
    assert (result.flagged_turns, extract.calls) == ([], 0)


def test_an_extract_failure_fails_the_item() -> None:
    two, _, _ = pipeline(
        {"send": Label.COMMITMENT}, {}, extract_answer=lambda _: ModelUnavailable("down")
    )
    with pytest.raises(ModelUnavailable):
        asyncio.run(two.analyze(turns("I'll send it.")))


def test_describe_names_both_stages() -> None:
    two, _, _ = pipeline({}, {})
    configuration = two.describe()
    assert configuration.name == "two-stage"
    assert configuration.stages == {"screen": "claude-haiku-5-5", "extract": "claude-opus-5-5"}
    assert configuration.prompt_version == "v1"


# --- End to end: three spec utterances (docs/spec.md, items 1, 5 and 11) through the factory ---

HAIKU, OPUS = "claude-haiku-5-5", "claude-opus-5-5"
CALL_DATE = date(2026, 10, 21)


def canned(
    turn: int,
    label: Label,
    quote: str,
    *,
    owner: str | None = None,
    recipient: str | None = None,
    action: str | None = None,
    due_raw: str | None = None,
    hint: Precision = Precision.NONE,
    condition: str | None = None,
) -> ModelSpan:
    return ModelSpan(
        turn_index=turn,
        label=label,
        owner=owner,
        recipient=recipient,
        action=action,
        due=ModelDue(raw=due_raw, precision_hint=hint),
        condition=condition,
        confidence=0.9,
        quote=quote,
        rationale="canned",
        ambiguous=False,
    )


def run_two_stage(
    speakers_and_texts: list[tuple[str, str]],
    screen: list[ModelSpan],
    extract: list[ModelSpan],
) -> tuple[AnalyzeResponse, FakeAdapter, FakeAdapter]:
    """The two-stage analyzer from the factory, each stage answering with its canned reply."""
    prompt = load_prompt("v1")
    screen_adapter = FakeAdapter(reply(ModelOutput(spans=screen), served_by=HAIKU), model=HAIKU)
    extract_adapter = FakeAdapter(reply(ModelOutput(spans=extract), served_by=OPUS), model=OPUS)
    adapters = {HAIKU: screen_adapter, OPUS: extract_adapter}
    analyzer = build_analyzer(
        Settings(_env_file=None),
        "two-stage",
        build=lambda model: Extractor(adapters[model], prompt),
    )
    request = AnalyzeRequest(
        transcript=[Turn(speaker=speaker, text=text) for speaker, text in speakers_and_texts],
        call_date=CALL_DATE,
    )
    response = asyncio.run(analyzer.analyze(request))
    return response, screen_adapter, extract_adapter


def as_dicts(spans: list[Span]) -> list[dict[str, object]]:
    keep = {"turn_index", "label", "owner", "recipient", "action", "condition", "due", "quote"}
    return [span.model_dump(include=keep) for span in spans]


PRICING = "I'll send you the revised pricing by Friday."
INVOICE_REQUEST = "Can you resend the invoice?"
INVOICE_REPLY = "Sure, I'll do it this afternoon."
INTEGRATION = "If legal signs off, we'll ship the integration on the 1st."


def test_spec_item_1_due_by_friday_resolves_to_the_friday_after_the_call() -> None:
    response, screen, extract = run_two_stage(
        [("seller", PRICING)],
        screen=[
            canned(
                0,
                Label.COMMITMENT,
                PRICING,
                owner="seller",
                action="send revised pricing",
                due_raw="by Friday",
                hint=Precision.DAY,
            )
        ],
        extract=[
            canned(
                0,
                Label.COMMITMENT,
                PRICING,
                owner="seller",
                action="send revised pricing",
                due_raw="by Friday",
                hint=Precision.DAY,
            ),
            # Not a substring of the turn, so the quote check drops it.
            canned(0, Label.SUGGESTION, "We should also book a demo"),
        ],
    )
    assert as_dicts(response.spans) == [
        {
            "turn_index": 0,
            "label": Label.COMMITMENT,
            "owner": "seller",
            "recipient": None,
            "action": "send revised pricing",
            "condition": None,
            "due": {"raw": "by Friday", "resolved": date(2026, 10, 23), "precision": Precision.DAY},
            "quote": PRICING,
        }
    ]
    assert response.metadata.dropped_quotes == 1
    assert (len(screen.requests), len(extract.requests)) == (1, 1)


def test_spec_item_5_the_extract_stage_sees_the_prior_turn_and_only_judges_the_flagged_one() -> (
    None
):
    # The screen misses the request (turn 0) and flags the reply (turn 1). The extract window is
    # turns 0-1; the REQUEST it gives turn 0 is context and must not reach the response.
    response, _, extract = run_two_stage(
        [("A", INVOICE_REQUEST), ("B", INVOICE_REPLY)],
        screen=[
            canned(
                1,
                Label.COMMITMENT,
                INVOICE_REPLY,
                owner="B",
                recipient="A",
                action="resend the invoice",
                due_raw="this afternoon",
                hint=Precision.DAY,
            )
        ],
        extract=[
            canned(0, Label.REQUEST, INVOICE_REQUEST),
            canned(
                1,
                Label.COMMITMENT,
                INVOICE_REPLY,
                owner="B",
                recipient="A",
                action="resend the invoice",
                due_raw="this afternoon",
                hint=Precision.DAY,
            ),
        ],
    )
    assert sent_turns(extract.requests[0]) == [INVOICE_REQUEST, INVOICE_REPLY]
    assert as_dicts(response.spans) == [
        {
            "turn_index": 1,
            "label": Label.COMMITMENT,
            "owner": "B",
            "recipient": "A",
            "action": "resend the invoice",
            "condition": None,
            "due": {"raw": "this afternoon", "resolved": CALL_DATE, "precision": Precision.DAY},
            "quote": INVOICE_REPLY,
        }
    ]
    assert response.metadata.dropped_quotes == 0


def test_spec_item_11_conditional_due_on_the_1st_resolves_to_the_next_first() -> None:
    # Three filler turns put the utterance at index 3, so its window starts at turn 1. The extract
    # model answers in window-relative indices (2), and the response must use the call's (3).
    call = [
        ("seller", "Hi, thanks for taking the call."),
        ("buyer", "Happy to. How is the rollout going?"),
        ("seller", "Good. Legal is still reviewing the contract."),
        ("seller", INTEGRATION),
    ]

    def item_11(turn: int) -> ModelSpan:
        return canned(
            turn,
            Label.CONDITIONAL,
            INTEGRATION,
            owner="seller",
            action="ship the integration",
            due_raw="on the 1st",
            hint=Precision.DAY,
            condition="legal sign-off",
        )

    response, screen, extract = run_two_stage(call, screen=[item_11(3)], extract=[item_11(2)])
    assert sent_turns(extract.requests[0]) == [text for _, text in call[1:]]
    assert as_dicts(response.spans) == [
        {
            "turn_index": 3,
            "label": Label.CONDITIONAL,
            "owner": "seller",
            "recipient": None,
            "action": "ship the integration",
            "condition": "legal sign-off",
            "due": {"raw": "on the 1st", "resolved": date(2026, 11, 1), "precision": Precision.DAY},
            "quote": INTEGRATION,
        }
    ]
    assert response.metadata.model == "two-stage"
    assert response.metadata.served_by == OPUS
