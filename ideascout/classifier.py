"""Ollama-based classifier for ingested posts.

Calls a local LLM (default qwen2.5:14b) to score each post on the 5-signal
demand framework. Designed to be resumable: posts already classified at the
active classifier_version are skipped.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CLASSIFIER_CONFIG = (
    Path(__file__).resolve().parent.parent / "config" / "classifier.yaml"
)

# Fixed enums — kept in code so the classifier and DB stay aligned. The
# user_preferences.yaml overrides domain *weights*, not the domain set.
DOMAIN_TAGS = [
    "tabletop_gaming",
    "kids_content",
    "ai_builders",
    "3d_printing",
    "video_games",
    "music",
    "general_b2b",
    "general_consumer",
    "developer_tools",
    "creator_tools",
    "finance",
    "health",
    "productivity",
    "education",
    "ecommerce",
]

SIGNAL_TYPES = {
    "asking_for_tool",
    "describing_pain",
    "success_story",
    "news",
    "show_and_tell",
    "other",
}

PROMPT_V1 = """You are an idea-scouting analyst for a solo developer who can ship a working web app in 1-2 days. Classify the post below.

SOURCE: {source_name}
TITLE: {title}
BODY: {body}

Return ONLY valid JSON matching this schema. No commentary, no markdown fence.

{{
  "is_demand_signal": <bool>,
  "demand_confidence": <float between 0.0 and 1.0>,
  "signal_type": <one of: "asking_for_tool", "describing_pain", "success_story", "news", "show_and_tell", "other">,
  "domain_tags": <array of 1-3 strings from THIS LIST ONLY: {domain_tags}>,
  "urgency_score": <int 1-5>,
  "solo_buildable_score": <int 1-5>,
  "workaround_pain": <int 1-5>,
  "payment_evidence": <int 1-5>,
  "niche_specificity": <int 1-5>,
  "summary": <string, max 200 chars>
}}

Scoring rules — be honest, not generous:
- is_demand_signal=true ONLY if the author is asking for a tool, describing a manual workaround that begs to be automated, or expressing willingness to pay for a missing solution. False for general discussion, news links, sharing wins, "show HN" launches, or pure venting without a clear tool gap.
- demand_confidence: 0.0 if not a signal; 1.0 if explicit "I would pay $X for this"; 0.7 if clear unmet need with implied payment willingness; 0.4 if vague request.
- urgency_score: 5 = "I would pay today / actively shopping". 4 = active need this month. 3 = nice-to-have. 2 = passing thought. 1 = no urgency.
- solo_buildable_score: 5 = solo dev ships useful version in <2 weeks. 3 = solo possible with effort. 1 = requires team / regulated industry / capital / hardware.
- workaround_pain: 5 = author describes hours/week spent manually. 3 = author mentions a clunky existing tool. 1 = no manual workaround mentioned.
- payment_evidence: 5 = mentions current paid tool, budget, or specific price they'd pay. 3 = compares to paid alternatives. 1 = no payment signal.
- niche_specificity: 5 = requires deep domain knowledge to build correctly. 3 = some niche understanding needed. 1 = generic problem any dev can solve.
- domain_tags: pick 1-3 most relevant. Use general_consumer / general_b2b only when no niche fits.
- summary: ONE sentence describing the underlying need (not the post content). Format: "User wants X for Y context."

Output the JSON now."""


@dataclass(slots=True)
class Classification:
    is_demand_signal: bool
    demand_confidence: float
    signal_type: str
    domain_tags: list[str]
    urgency_score: int
    solo_buildable_score: int
    workaround_pain: int
    payment_evidence: int
    niche_specificity: int
    summary: str

    def to_db_row(self) -> dict:
        return {
            "is_demand_signal": 1 if self.is_demand_signal else 0,
            "demand_confidence": float(self.demand_confidence),
            "signal_type": self.signal_type,
            "domain_tags": json.dumps(self.domain_tags),
            "urgency_score": int(self.urgency_score),
            "solo_buildable_score": int(self.solo_buildable_score),
            "workaround_pain": int(self.workaround_pain),
            "payment_evidence": int(self.payment_evidence),
            "niche_specificity": int(self.niche_specificity),
            "summary": self.summary,
        }


class ClassifierError(Exception):
    """Raised when a post cannot be classified after retries."""


def _coerce_int_1_5(v, field: str) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError) as e:
        raise ValueError(f"{field}: not numeric ({v!r})") from e
    return max(1, min(5, n))


def _coerce_float_0_1(v, field: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{field}: not numeric ({v!r})") from e
    return max(0.0, min(1.0, x))


def parse_response(raw_text: str) -> Classification:
    """Tolerant parser — strips markdown fences and extracts JSON."""
    s = raw_text.strip()
    # If the model wrapped output in a fence, strip it.
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    # Find the JSON object boundaries if there's leading/trailing prose.
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in response: {raw_text[:200]!r}")
    s = s[start : end + 1]
    try:
        d = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}; raw={raw_text[:200]!r}") from e

    signal_type = str(d.get("signal_type", "other"))
    if signal_type not in SIGNAL_TYPES:
        signal_type = "other"

    raw_tags = d.get("domain_tags") or []
    if not isinstance(raw_tags, list):
        raw_tags = [raw_tags]
    domain_tags = [t for t in (str(x) for x in raw_tags) if t in DOMAIN_TAGS]
    if not domain_tags:
        domain_tags = ["general_consumer"]

    summary = str(d.get("summary", "")).strip()[:300]

    return Classification(
        is_demand_signal=bool(d.get("is_demand_signal", False)),
        demand_confidence=_coerce_float_0_1(
            d.get("demand_confidence", 0.0), "demand_confidence"
        ),
        signal_type=signal_type,
        domain_tags=domain_tags,
        urgency_score=_coerce_int_1_5(d.get("urgency_score", 1), "urgency_score"),
        solo_buildable_score=_coerce_int_1_5(
            d.get("solo_buildable_score", 1), "solo_buildable_score"
        ),
        workaround_pain=_coerce_int_1_5(
            d.get("workaround_pain", 1), "workaround_pain"
        ),
        payment_evidence=_coerce_int_1_5(
            d.get("payment_evidence", 1), "payment_evidence"
        ),
        niche_specificity=_coerce_int_1_5(
            d.get("niche_specificity", 1), "niche_specificity"
        ),
        summary=summary,
    )


@dataclass(slots=True)
class ClassifierConfig:
    version: str
    model: str
    ollama_url: str
    prompt: str


def load_classifier_config(
    path: Path = DEFAULT_CLASSIFIER_CONFIG,
) -> ClassifierConfig:
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    active = cfg.get("active_version", "v1.0")
    versions = cfg.get("versions", {})
    spec = versions.get(active, {})
    return ClassifierConfig(
        version=active,
        model=spec.get("model", "qwen2.5:14b"),
        ollama_url=spec.get("ollama_url", "http://localhost:11434"),
        prompt=PROMPT_V1,
    )


class OllamaClassifier:
    """Stateless wrapper around Ollama /api/generate."""

    def __init__(self, config: ClassifierConfig):
        self.config = config

    def healthcheck(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{self.config.ollama_url}/api/tags", method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read())
            names = {m.get("name", "") for m in payload.get("models", [])}
            return self.config.model in names
        except Exception:
            return False

    def classify_post(
        self, *, source_name: str, title: str, body: str, max_body_chars: int = 4000
    ) -> Classification:
        body_trimmed = (body or "")[:max_body_chars]
        prompt = self.config.prompt.format(
            source_name=source_name,
            title=title,
            body=body_trimmed or "(no body)",
            domain_tags=", ".join(DOMAIN_TAGS),
        )
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_ctx": 8192,
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.ollama_url}/api/generate",
            data=body_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                response_payload = json.loads(resp.read())
        except urllib.error.URLError as e:
            raise ClassifierError(f"Ollama request failed: {e}") from e

        raw_text = response_payload.get("response", "")
        if not raw_text:
            raise ClassifierError(f"empty response from Ollama: {response_payload}")

        try:
            return parse_response(raw_text)
        except ValueError as e:
            raise ClassifierError(str(e)) from e
