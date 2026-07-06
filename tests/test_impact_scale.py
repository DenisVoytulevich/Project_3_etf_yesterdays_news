"""Тесты единой шкалы «Влияние»."""

from src.report.impact_scale import (
    format_impact_score,
    impact_sentiment,
    is_valid_impact_score,
    parse_impact_score,
)


def test_parse_impact_score():
    assert parse_impact_score("+3") == 3
    assert parse_impact_score("−2") == -2
    assert parse_impact_score("-5") == -5
    assert parse_impact_score("0") == 0


def test_format_impact_score():
    assert format_impact_score("+3") == "+3"
    assert format_impact_score("-2") == "-2"


def test_impact_sentiment():
    assert impact_sentiment("+2") == "positive"
    assert impact_sentiment("−3") == "negative"
    assert impact_sentiment("0") == "neutral"


def test_is_valid_impact_score():
    assert is_valid_impact_score("+5")
    assert not is_valid_impact_score("+9")
    assert not is_valid_impact_score("высокая")
