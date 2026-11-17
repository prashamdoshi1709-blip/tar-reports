"""MODE A AI writer (Google Gemini free tier) and the offline fixture writer.

The AI returns the TAR report content as JSON (response JSON schema). If tar_gen.checks or the layout measurement finds
problems, the conversation continues with the exact problems listed (up to max_attempts). The key comes from the
GEMINI_API_KEY secret only. The AI never writes the company identity, date, sources line, disclaimer or hashtag rules:
those are fixed by the pipeline. MODE B (no AI at all) is tar_gen/template.py.
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


class GeminiWriter:
    """MODE A: Google Gemini API, free tier (no billing account). Plain HTTPS to the generativelanguage REST endpoint.

    Data rule: the free ("unpaid") Gemini API terms allow Google to use prompts and responses to improve its products,
    including human review, and ask users not to submit confidential information. This writer therefore refuses to run
    unless config vitti_generator.gemini_data_use_authorised is true (the owner's explicit permission to send Vitti
    material to that service). Errors are classified so the pipeline can fall back to MODE B:
      AI_QUOTA (429 / RESOURCE_EXHAUSTED), AI_UNAVAILABLE (5xx, timeouts, network), AI_AUTH (401/403, bad key),
      AI_MODEL_UNAVAILABLE (no configured model is offered to this key), AI_BLOCKED (safety block), AI_BAD_JSON."""
    mode = "A-gemini"

    def __init__(self, models, authorised, key=None, timeout=120, pause=None):
        import requests
        self.requests = requests
        if authorised is not True:
            raise GenError("AI_NOT_AUTHORISED", "sending Vitti material to Gemini is not authorised (gemini_data_use_authorised=false)")
        self.key = (key if key is not None else os.environ.get("GEMINI_API_KEY", "")).strip()
        if not self.key:
            raise GenError("AI_NOT_CONFIGURED", "GEMINI_API_KEY secret is not set")
        self.timeout = timeout
        self.pause = float(os.environ.get("TAR_GEMINI_PAUSE", "5")) if pause is None else pause
        self.base = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com").rstrip("/")
        self.usage = []
        self.model = self._pick(models)

    def _call(self, method, path, body=None):
        url = f"{self.base}/v1beta/{path}"
        last = None
        for attempt in range(3):
            try:
                r = self.requests.request(method, url, json=body, timeout=self.timeout,
                                          headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
            except self.requests.RequestException as e:
                last = GenError("AI_UNAVAILABLE", f"Gemini request failed ({type(e).__name__})", transient=True)
            else:
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 429:
                    raise GenError("AI_QUOTA", "Gemini free-tier quota exhausted or rate limited (HTTP 429)", transient=True)
                if r.status_code in (401, 403):
                    raise GenError("AI_AUTH", f"Gemini rejected the API key or project (HTTP {r.status_code})")
                if r.status_code == 404:
                    raise GenError("AI_MODEL_UNAVAILABLE", "Gemini model not found for this key (HTTP 404)")
                if r.status_code == 400:
                    raise GenError("AI_BAD_REQUEST", "Gemini rejected the request (HTTP 400)")
                last = GenError("AI_UNAVAILABLE", f"Gemini answered HTTP {r.status_code}", transient=True)
            import time; time.sleep(self.pause * (attempt + 1))
        raise last

    def _pick(self, models):
        """Use the first configured model that this key can actually call (checked live, never assumed)."""
        names, token = set(), None
        while True:
            j = self._call("GET", "models?pageSize=1000" + (f"&pageToken={token}" if token else ""))
            for m in j.get("models", []):
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    names.add(m["name"].split("/", 1)[-1])
            token = j.get("nextPageToken")
            if not token:
                break
        for m in models:
            if m in names:
                return m
        raise GenError("AI_MODEL_UNAVAILABLE", "none of the configured Gemini models is offered to this key: " + ", ".join(models))

    def start(self, ident):
        return [{"role": "user", "content": user_prompt(ident)}]

    def generate(self, contents, schema=True):
        cfg = {"responseMimeType": "application/json", "temperature": 0.2}
        if schema:
            cfg["responseJsonSchema"] = SCHEMA
        body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": contents, "generationConfig": cfg}
        try:
            return self._call("POST", f"models/{self.model}:generateContent", body)
        except GenError as e:
            if e.code == "AI_BAD_REQUEST" and schema:  # older endpoint without JSON-schema support: the checks still validate shape
                return self._call("POST", f"models/{self.model}:generateContent", dict(body, generationConfig={k: v for k, v in cfg.items() if k != "responseJsonSchema"}))
            raise

    def complete(self, messages):
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages]
        j = self.generate(contents)
        if (j.get("promptFeedback") or {}).get("blockReason"):
            raise GenError("AI_BLOCKED", "Gemini blocked the prompt")
        cands = j.get("candidates") or []
        if not cands:
            raise GenError("AI_BAD_JSON", "Gemini returned no candidate")
        fin = cands[0].get("finishReason")
        if fin in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
            raise GenError("AI_BLOCKED", f"Gemini stopped the reply ({fin})")
        if fin == "MAX_TOKENS":
            raise GenError("AI_TRUNCATED", "Gemini reply was cut off")
        text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []))
        u = j.get("usageMetadata") or {}
        self.usage.append({"model": self.model, "input_tokens": u.get("promptTokenCount"), "output_tokens": u.get("candidatesTokenCount")})
        try:
            rep = json.loads(text)
        except ValueError:
            raise GenError("AI_BAD_JSON", "Gemini reply was not valid JSON")
        if not isinstance(rep, dict):
            raise GenError("AI_BAD_JSON", "Gemini reply was not a JSON object")
        return rep, text

    def ping(self):
        """Synthetic, data-free call: proves the free-tier key can generate (no Vitti material is sent)."""
        j = self._call("POST", f"models/{self.model}:generateContent",
                       {"contents": [{"role": "user", "parts": [{"text": "Reply with the single word OK."}]}],
                        "generationConfig": {"temperature": 0}})
        return bool(j.get("candidates"))


class FixtureWriter:
    """Offline stand-in: returns prepared report JSON objects in order (tests and historical replays without an API key)."""
    mode = "fixture"
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
