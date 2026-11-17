"""AI report writer: Claude (Anthropic API) turns one Vitti Daily Mover package into the TAR report content as JSON.

One streamed Messages API call with structured output (output_config.format = JSON schema) so the reply always parses.
If tar_gen.checks or the layout measurement finds problems, the same conversation continues with the exact problems
listed (up to max_attempts). The API key comes from ANTHROPIC_API_KEY only. The model never sees or writes the company
identity, date, sources line, disclaimer or hashtag rules: those are fixed by the pipeline.
"""
import json, os

from .common import GenError, long_date

ITEM = {"type": "object", "additionalProperties": False, "required": ["head", "body"],
        "properties": {"head": {"type": "string"}, "body": {"type": "string"}}}

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "headline", "topic", "lede", "kpis", "chart", "facts_label", "facts", "context_label", "context",
                 "why", "watch", "take", "caption"],
    "properties": {
        "title": {"type": "string", "description": "LinkedIn document title, under 55 characters, e.g. 'Example Co: $85M Offtake Deal Signed'"},
        "headline": {"type": "string", "description": "page-1 headline, one plain sentence, 50-110 characters"},
        "topic": {"type": "string", "description": "short event label for the meta line, e.g. 'Scheme implementation deed'"},
        "lede": {"type": "string", "description": "2-3 sentences: what happened, the share move in morning trade, why it matters"},
        "kpis": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["value", "label", "note", "tone"],
                                            "properties": {"value": {"type": "string"}, "label": {"type": "string"},
                                                           "note": {"type": "string"}, "tone": {"type": "string", "enum": ["teal", "orange", "navy"]}}}},
        "chart": {"type": "object", "additionalProperties": False, "required": ["include", "label", "note", "bars"],
                  "properties": {"include": {"type": "boolean"}, "label": {"type": "string"}, "note": {"type": "string"},
                                 "bars": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                     "required": ["label", "value", "display"],
                                                                     "properties": {"label": {"type": "string"}, "value": {"type": "number"},
                                                                                    "display": {"type": "string"}}}}}},
        "facts_label": {"type": "string"}, "facts": {"type": "array", "items": ITEM},
        "context_label": {"type": "string"}, "context": {"type": "array", "items": ITEM},
        "why": {"type": "array", "items": ITEM}, "watch": {"type": "array", "items": ITEM},
        "take": {"type": "string"},
        "caption": {"type": "object", "additionalProperties": False,
                    "required": ["intro", "context", "key_points", "looking_ahead", "we_look_at", "hashtags"],
                    "properties": {"intro": {"type": "string"}, "context": {"type": "string"},
                                   "key_points": {"type": "array", "items": {"type": "string"}},
                                   "looking_ahead": {"type": "string"},
                                   "we_look_at": {"type": "array", "items": {"type": "string"}},
                                   "hashtags": {"type": "array", "items": {"type": "string"}}}},
    },
}

SYSTEM = """You write The Announcement Room (TAR): a two-page investor report and its LinkedIn caption about one ASX company's announcement, for busy retail investors. TAR explains what happened, why it matters and what comes next.

Your only source is the material in the user message: the Vitti Capital Daily Mover (a one-page analyst snapshot) and, when supplied, the company's own ASX announcement(s) of the same day that Vitti sent with it. TAR does not do its own research.

Accuracy rules (an automated checker enforces them and rejects the report otherwise):
- Every figure you write (amounts, percentages, prices, multiples, counts with units, dates' days) must appear in the source material exactly as written there. Do not round, convert currencies or units, annualise, add, subtract or compute anything. If a comparison is not stated in the source, describe it without a number.
- Keep currency symbols exactly as the source shows them (do not add A$, NZ$ or US$ unless the source does).
- The share move in the Daily Mover is an intraday figure from morning trade, not a close. Say "in morning trade". Never write clock times.
- Company guidance, targets and expectations are not results: label them as guidance or targets.
- Where Vitti gives a reason for the move, attribute it ("Vitti points to ..."); do not present it as certain.
- Mention no other ASX code than the company's own. Do not name Vitti's analyst.
- Never use the words "draft" or "approved". Never use em dashes. No personal advice, no buy/sell/hold language, no price targets.

Style: Australian English, plain words, short sentences, active voice, no hype or exclamation marks, no emojis. Write for an intelligent reader who has not seen the announcement. Each item heading is a short phrase; each body is one or two sentences.

Layout (two fixed pages; lengths matter, the pipeline measures the real layout):
- title: under 55 characters, "<Short company name>: <what happened>".
- headline: one sentence, 50-110 characters. lede: 2-3 sentences, under 430 characters.
- kpis: 3 or 4 headline figures from the source; value is the bare figure (max 12 characters, e.g. "+12.4%", "$1.25", "$85.0M"), label names it, note adds context (max 75 characters). Use tone "orange" for the share move, "teal" for the main deal or result figure, "navy" otherwise.
- chart: include only if the Daily Mover itself shows a chart series; copy its 2-6 values exactly (value as a number, display as written, e.g. "$34.2m FY26"); label is an upper-case-style caption sentence. Otherwise include=false, empty label/note, no bars.
- facts: 3-5 items, what the announcement says. context: 2-4 items, how we got here (earlier events from the source timeline).
- why: exactly 3 items, why investors appeared to focus on it. watch: 3-4 items, what investors should watch next (approvals, dates, risks the source names).
- take: the TAR take, 3-4 balanced sentences weighing what is positive against what is still uncertain, under 560 characters.
- caption: intro starts "According to the Vitti Capital Daily Mover dated <date>, <company> ..." and states the move and the news; context adds the second most important point; key_points 3-6 short bullets (no bullet symbols); looking_ahead starts "Looking ahead, ..."; we_look_at exactly 4 short phrases describing the report's sections; hashtags 1-3 words such as the company's short name and its sector, without '#'."""


def user_prompt(ident):
    parts = [f"Company: {ident.company}\nASX code: {ident.ticker}\nReport date: {long_date(ident.date)}\n"
             f"Vitti email subject: {ident.subject}\n",
             "=== VITTI CAPITAL DAILY MOVER (text extracted from the PDF; letter-spaced labels were joined) ===\n" + ident.dm_text]
    for name, text in ident.support:
        parts.append(f"=== COMPANY ASX ANNOUNCEMENT SUPPLIED WITH THE DAILY MOVER: {name} ===\n{text}")
    parts.append("Write the TAR report for this announcement as JSON matching the schema.")
    return "\n\n".join(parts)


class ClaudeWriter:
    def __init__(self, model, effort="high", max_tokens=32000):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise GenError("DEPENDENCY", f"anthropic SDK is not installed ({e})")
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            raise GenError("ANTHROPIC_SECRET_MISSING", "ANTHROPIC_API_KEY secret is not set")
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=4, timeout=600)
        self.model, self.effort, self.max_tokens = model, effort, max_tokens
        self.usage = []

    def start(self, ident):
        return [{"role": "user", "content": user_prompt(ident)}]

    def complete(self, messages):
        """Returns (report_dict, assistant_content_to_append). Raises GenError (transient for API outages)."""
        a = self.anthropic
        try:
            with self.client.beta.messages.stream(
                model=self.model, max_tokens=self.max_tokens, system=SYSTEM, messages=messages,
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            ) as stream:
                msg = stream.get_final_message()
        except (a.RateLimitError, a.InternalServerError, a.APIConnectionError, a.APITimeoutError) as e:
            raise GenError("AI_UNAVAILABLE", f"Anthropic API unavailable after retries ({type(e).__name__})", transient=True)
        except a.AuthenticationError:
            raise GenError("AI_AUTH", "ANTHROPIC_API_KEY was rejected (401)")
        except a.APIStatusError as e:
            raise GenError("AI_HTTP", f"Anthropic API error HTTP {e.status_code}", transient=e.status_code >= 500)
        self.usage.append({"model": msg.model, "input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens})
        if msg.stop_reason == "refusal":
            raise GenError("AI_REFUSAL", "the model declined this request")
        if msg.stop_reason == "max_tokens":
            raise GenError("AI_TRUNCATED", "the model reply was cut off at max_tokens")
        text = next((b.text for b in msg.content if b.type == "text"), None)
        try:
            rep = json.loads(text)
        except (TypeError, ValueError):
            raise GenError("AI_BAD_JSON", "the model reply was not valid JSON")
        return rep, msg.content


class FixtureWriter:
    """Offline stand-in: returns prepared report JSON objects in order (tests and historical replays without an API key)."""
    def __init__(self, reports):
        self.reports = list(reports)
        self.usage = []
        self.calls = 0

    def start(self, ident):
        return [{"role": "user", "content": user_prompt(ident)}]

    def complete(self, messages):
        self.calls += 1
        if not self.reports:
            raise GenError("AI_BAD_JSON", "fixture writer has no more replies")
        r = self.reports.pop(0)
        return json.loads(json.dumps(r)), [{"type": "text", "text": json.dumps(r)}]
