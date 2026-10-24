<!--
Evaluation-set generation prompt, v1. Model-agnostic: paste into Gemini, DeepSeek or any chat model.

Before pasting, replace every {{PLACEHOLDER}}:
  {{COUNT}}       items in this batch; 25 or fewer, since long outputs degrade and chat apps truncate
  {{ID_PREFIX}}   short and unique per batch, e.g. gem01 or dsk02
  {{CALL_DATE}}   ISO date of the call, e.g. 2026-11-04
  {{CALL_WEEKDAY}} that date's weekday, e.g. Wednesday (fill it in yourself; don't make the model work it out)
  {{DOMAIN}}      the business setting, e.g. "B2B SaaS sales calls" or "agency-client project check-ins"
  {{SPEAKERS}}    the two role ids, e.g. "seller and buyer" or "account_manager and client"
  {{LABEL_MIX}}   how many items to centre on each label, e.g. "4 COMMITMENT, 3 HEDGED, 3 CONDITIONAL, ..."
  {{MULTI_TURN}}  how many of the items are multi-turn snippets where context decides the label

Save the reply as a .jsonl file and run `uv run eval import`. Everything the model writes is a draft: labels are
reviewed blind before any item is scored. Change this prompt by adding prompt-v2.md, never by editing this one.
-->

# Task

You are writing evaluation data for a system that reads business conversation transcripts and extracts
commitments: who promised what, to whom, and by when. Write {{COUNT}} test items in the setting of
**{{DOMAIN}}**, between two speakers whose ids are **{{SPEAKERS}}**. The call took place on **{{CALL_DATE}}, a
{{CALL_WEEKDAY}}**.

The data will be used to find where the system fails, so realistic hard cases matter more than easy ones. Every
label you give must be one a careful human annotator would agree with.

# The eight labels

Each span (a statement inside one turn) gets exactly one label.

| Label | Meaning | Ledger |
| --- | --- | --- |
| COMMITMENT | The speaker binds themselves, their team, or a colleague they assign, to a specific action. | yes |
| HEDGED | An action is named, but the obligation is softened or vague ("I'll try", "should be able to", "hopefully", "we'll circle back"). | yes, soft |
| CONDITIONAL | A commitment that depends on a stated condition ("if legal signs off", "as long as the PO is approved"). | yes |
| SUGGESTION | An idea or proposal with no owner bound to it ("we should probably…", "it might make sense to…"). | no |
| REQUEST | Asks the other party to act ("can you…", "would you be able to…"). | no |
| REPORTED | A third party's promise, retold ("Sarah said she'd send it"). | no |
| REFUSAL | Explicitly declines or withholds a commitment ("I can't promise the 15th"). | no |
| NONE | Facts, past events, policy statements, small talk, sarcasm. | no |

**Decision rules for borderline cases**

- Words decide nothing on their own. "Promise" can be REFUSAL ("I can't promise…"), REPORTED ("our CEO promised
  them…") or NONE ("last quarter I promised a rebate and we delivered it"). Items like these are keyword traps.
- A reply such as "Sure, I'll do it this afternoon" after a request is a COMMITMENT by the person replying; the
  request itself is a REQUEST. Without the prior turn, "Will do." is NONE.
- "We will…" binds the speaker's team: the owner is the speaker's id.
- A speaker assigning a named colleague ("…and Priya will set up the account") makes a COMMITMENT owned by that
  colleague.
- Past or already-fulfilled promises are NONE. Ongoing policy ("our SLA is four hours") is NONE.
- Obvious sarcasm is NONE.
- If even a careful annotator could reasonably go either way, still give your best label but add the tag
  `ambiguous` and explain in `note`. Use this for no more than 1 in 20 items; ambiguity is not a way out of hard
  calls.

# Fields for each expected span

| Field | Rule |
| --- | --- |
| `turn_index` | 0-based index of the turn the span is in. |
| `label` | One of the eight labels, upper case. |
| `quote` | Copied character for character from that turn, punctuation included. Use the whole turn when the turn is one statement; use the exact clause when one turn holds two spans. |
| `owner` | Required for COMMITMENT, HEDGED and CONDITIONAL: a speaker id, or the named person exactly as written. For REPORTED, the third party. For REFUSAL, the speaker. Otherwise null. |
| `recipient` | For COMMITMENT, HEDGED, CONDITIONAL and REFUSAL: the other speaker's id. For REQUEST: the id of the speaker who asked. For SUGGESTION: the listener's id if the idea is aimed at them, else null. For REPORTED: whoever the promise was made to if stated, else null. For NONE: null. |
| `action_keywords` | 1 to 3 lower-case words that any correct description of the action must contain, such as `["send", "pricing"]`. Empty list when no concrete action is named (e.g. "we'll circle back on that") and for NONE. |
| `due_raw` | The deadline words exactly as spoken ("by Friday", "end of next week", "before your board meeting"), or null. |
| `precision` | `day`, `week`, `event` (tied to an event, like "after the pilot"), `vague` ("soon", "at some point") or `none`. |
| `due_resolved` | ISO date, only for `day` or `week` precision; otherwise null. Rules below. |
| `condition` | Required for CONDITIONAL: the condition in a few words, e.g. "legal sign-off". Otherwise null. |

**Due-date rules** (relative to {{CALL_DATE}}, a {{CALL_WEEKDAY}})

- Weeks start on Monday. A `week` precision date is the Monday of that week: "this week" is the Monday on or
  before the call date; "next week" is the Monday after that.
- "End of the week" and "end of next week" are `day` precision: the Friday of that week.
- A bare weekday ("Monday", "by Friday") is the next such day strictly after the call date. "Next Tuesday" is the
  Tuesday of the following calendar week.
- "The 1st", "the 15th" is the next such day of a month after the call date.
- "Today", "end of day" is the call date; "tomorrow" is the next day. "In two weeks" adds 14 days.
- "Before <date>" is the day before that date. A phrase tied to an event has precision `event` and no date.
- A past deadline ("last week") inside a REPORTED or NONE span has precision `none` and no date.

# Output format

Output only JSON Lines: one item per line, no array, no markdown fences, no commentary before or after. Each line
has exactly these keys, and no others:

- `id`: "{{ID_PREFIX}}-01", "{{ID_PREFIX}}-02", …
- `call_date`: "{{CALL_DATE}}"
- `turns`: list of `{"speaker": "<id>", "text": "<what they said>"}`
- `tags`: any of `"multi_turn"` (more than one turn), `"keyword_trap"`, `"ambiguous"`; empty list if none apply
- `expected`: list of spans with every field above, in turn order. At least one span per item. Give a span for
  every statement whose label is not NONE; a single-turn item that is NONE gets one NONE span. Neutral turns inside
  a multi-turn snippet may be left out.
- `note`: one short sentence on why the label is right and what makes the item hard, or null

These two example lines show the format. Do not reuse, reword or lightly vary them, or the other examples
quoted above; write new situations.

{"id": "ex-01", "call_date": "2026-10-21", "turns": [{"speaker": "buyer", "text": "Can you resend the invoice?"}, {"speaker": "seller", "text": "Sure, I'll do it this afternoon."}], "tags": ["multi_turn"], "expected": [{"turn_index": 0, "label": "REQUEST", "quote": "Can you resend the invoice?", "owner": null, "recipient": "buyer", "action_keywords": ["resend", "invoice"], "due_raw": null, "due_resolved": null, "precision": "none", "condition": null}, {"turn_index": 1, "label": "COMMITMENT", "quote": "Sure, I'll do it this afternoon.", "owner": "seller", "recipient": "buyer", "action_keywords": ["invoice"], "due_raw": "this afternoon", "due_resolved": "2026-10-21", "precision": "day", "condition": null}], "note": "the commitment only makes sense with the prior request"}
{"id": "ex-02", "call_date": "2026-10-21", "turns": [{"speaker": "seller", "text": "I can't promise we'll hit the 15th."}], "tags": ["keyword_trap"], "expected": [{"turn_index": 0, "label": "REFUSAL", "quote": "I can't promise we'll hit the 15th.", "owner": "seller", "recipient": "buyer", "action_keywords": [], "due_raw": null, "due_resolved": null, "precision": "none", "condition": null}], "note": "contains 'promise' but negated"}

# What makes a good batch

- **Label mix:** centre the items on {{LABEL_MIX}}. {{MULTI_TURN}} of them are multi-turn snippets (2 to 5 turns)
  where an earlier turn changes the label of a later one.
- **Hard cases:** about a third should be traps: trigger words used in non-commitments, commitments with no
  trigger words ("leave the redlines with me"), hedges that sound firm, conditions buried mid-sentence, a refusal
  followed by a counter-offer, two spans with different labels in one turn, a request answered vaguely.
- **Variety:** vary length (3 to 40 words per turn), formality, filler and false starts as in real speech
  ("yeah, so, um, I'll get that over"), deadline phrasing, and which speaker commits. Don't start most turns the
  same way.
- **Realism:** plausible names, products and situations for {{DOMAIN}}. No real companies or real people.

# Before you answer, check every line

1. Each `quote` appears exactly in its turn's `text`.
2. COMMITMENT, HEDGED and CONDITIONAL spans have an `owner`; CONDITIONAL spans have a `condition`.
3. `due_resolved` is set only for `day` or `week` precision and follows the date rules.
4. `action_keywords` are lower case and appear in, or are implied by, the quote.
5. The line parses as JSON and has exactly the keys listed.
