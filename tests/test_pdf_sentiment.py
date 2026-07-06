"""Тесты раскраски драйверов в PDF."""

from src.report.pdf import _driver_influence_sentiment


def test_insurance_losses_rising_is_negative():
    sentiment = _driver_influence_sentiment("Страховые убытки: рост")
    assert sentiment == "negative"


def test_fuel_cost_falling_is_positive_for_airlines():
    sentiment = _driver_influence_sentiment("Цена топлива: снижение")
    assert sentiment == "positive"


def test_logistics_costs_lower_is_positive_for_industry():
    sentiment = _driver_influence_sentiment("Топливо и логистика: издержки ниже")
    assert sentiment == "positive"


def test_transport_costs_fall_supports_demand():
    sentiment = _driver_influence_sentiment(
        "Транспортные расходы: снижение поддерживает спрос"
    )
    assert sentiment == "positive"


def test_oil_supply_growth_is_negative_for_energy():
    sentiment = _driver_influence_sentiment("Предложение нефти: рост")
    assert sentiment == "negative"


def test_brent_pressure_down_is_negative_for_energy():
    sentiment = _driver_influence_sentiment("Brent: давление вниз")
    assert sentiment == "negative"


def test_combined_energy_drivers_stay_negative():
    sentiment = _driver_influence_sentiment(
        "Предложение нефти: рост; Brent: давление вниз"
    )
    assert sentiment == "negative"
