import json

import pytest

from ideascout.classifier import (
    DOMAIN_TAGS,
    SIGNAL_TYPES,
    Classification,
    parse_response,
)


def _well_formed_payload(**overrides) -> dict:
    base = {
        "is_demand_signal": True,
        "demand_confidence": 0.85,
        "signal_type": "asking_for_tool",
        "domain_tags": ["tabletop_gaming"],
        "urgency_score": 4,
        "solo_buildable_score": 5,
        "workaround_pain": 4,
        "payment_evidence": 3,
        "niche_specificity": 5,
        "summary": "User wants paint inventory tracker for miniatures hobby.",
    }
    base.update(overrides)
    return base


def test_parse_response_happy_path():
    raw = json.dumps(_well_formed_payload())
    c = parse_response(raw)
    assert isinstance(c, Classification)
    assert c.is_demand_signal is True
    assert 0 <= c.demand_confidence <= 1
    assert c.signal_type in SIGNAL_TYPES
    assert all(t in DOMAIN_TAGS for t in c.domain_tags)
    assert 1 <= c.urgency_score <= 5
    assert c.summary.startswith("User wants paint")


def test_parse_response_strips_markdown_fence():
    raw = "```json\n" + json.dumps(_well_formed_payload()) + "\n```"
    c = parse_response(raw)
    assert c.is_demand_signal is True


def test_parse_response_strips_leading_prose():
    raw = "Sure, here is the JSON:\n" + json.dumps(_well_formed_payload())
    c = parse_response(raw)
    assert c.summary


def test_parse_response_clamps_out_of_range_scores():
    raw = json.dumps(
        _well_formed_payload(
            urgency_score=99, solo_buildable_score=-3, demand_confidence=2.5
        )
    )
    c = parse_response(raw)
    assert c.urgency_score == 5
    assert c.solo_buildable_score == 1
    assert c.demand_confidence == 1.0


def test_parse_response_invalid_signal_type_falls_back_to_other():
    raw = json.dumps(_well_formed_payload(signal_type="invented"))
    c = parse_response(raw)
    assert c.signal_type == "other"


def test_parse_response_unknown_domain_tags_filtered():
    raw = json.dumps(
        _well_formed_payload(
            domain_tags=["tabletop_gaming", "fictional_domain", "kids_content"]
        )
    )
    c = parse_response(raw)
    assert c.domain_tags == ["tabletop_gaming", "kids_content"]


def test_parse_response_empty_domain_tags_defaults_to_general_consumer():
    raw = json.dumps(_well_formed_payload(domain_tags=[]))
    c = parse_response(raw)
    assert c.domain_tags == ["general_consumer"]


def test_parse_response_rejects_non_json():
    with pytest.raises(ValueError):
        parse_response("the model decided to refuse today")


def test_parse_response_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_response("{is_demand_signal: yes, urgency: bananas}")


def test_to_db_row_serialises_domain_tags_to_json():
    c = parse_response(json.dumps(_well_formed_payload()))
    row = c.to_db_row()
    assert row["is_demand_signal"] == 1
    decoded = json.loads(row["domain_tags"])
    assert decoded == ["tabletop_gaming"]


def test_classification_count_default_floor_when_missing_fields():
    raw = json.dumps({"is_demand_signal": False, "summary": "Just a discussion."})
    c = parse_response(raw)
    assert c.is_demand_signal is False
    assert c.urgency_score == 1
    assert c.solo_buildable_score == 1
    assert c.summary.startswith("Just a discussion")
