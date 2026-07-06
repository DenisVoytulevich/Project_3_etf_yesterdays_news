"""Тесты раскраски драйверов в PDF."""

from src.report.pdf import _driver_influence_sentiment


def test_insurance_losses_rising_is_negative():
    sentiment = _driver_influence_sentiment("Страховые убытки: рост")
    assert sentiment == "negative"


def test_fuel_cost_falling_is_positive_for_airlines():
    sentiment = _driver_influence_sentiment("Цена топлива: снижение")
    assert sentiment == "positive"
