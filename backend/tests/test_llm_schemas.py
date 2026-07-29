"""Malformed LLM output must be dropped item-by-item with a logged reason, never
crash the caller and never be silently trusted as-is — this is what makes
'do not return unvalidated AI output directly to the application' concrete."""
from backend.pipeline.llm_schemas import (
    ConflictResult,
    ProfanityItem,
    SentimentItem,
    SummaryResult,
    parse_indexed_items,
    parse_single,
)


def test_valid_items_all_pass_through():
    raw = [{"index": 0, "sentiment": "Positive"}, {"index": 1, "sentiment": "Negative"}]
    result = parse_indexed_items(raw, SentimentItem, context="test")
    assert [item.index for item in result] == [0, 1]
    assert [item.sentiment for item in result] == ["Positive", "Negative"]


def test_malformed_item_is_dropped_not_crashed_on():
    raw = [
        {"index": 0, "sentiment": "Positive"},
        {"sentiment": "Negative"},  # missing "index" — would KeyError on raw dict access
        {"index": 2, "sentiment": "Ecstatic"},  # not a valid Sentiment value
        "not even a dict",
    ]
    result = parse_indexed_items(raw, SentimentItem, context="test")
    assert len(result) == 1
    assert result[0].index == 0


def test_profanity_items_validate_bool_type():
    raw = [{"index": 0, "profane": True}, {"index": 1, "profane": "yes"}]
    # "yes" is coerced by pydantic's lenient bool parsing — still validates, since it's
    # an unambiguous truthy string, not a type-safety hole.
    result = parse_indexed_items(raw, ProfanityItem, context="test")
    assert len(result) == 2


def test_parse_single_returns_none_for_missing_or_malformed():
    assert parse_single(None, SummaryResult, context="test") is None
    assert parse_single({}, SummaryResult, context="test") is None
    assert parse_single({"not_summary": "x"}, SummaryResult, context="test") is None


def test_parse_single_returns_validated_model_for_good_input():
    result = parse_single({"conflict": True}, ConflictResult, context="test")
    assert result is not None
    assert result.conflict is True
