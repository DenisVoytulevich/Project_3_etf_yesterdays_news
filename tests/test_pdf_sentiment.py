"""Тесты раскраски драйверов и ширины колонок в PDF."""

from src.report.pdf import (
    _ReportPDF,
    _apply_reference_impact_col_width,
    _find_fonts,
    _fixed_table_col_widths,
    _reference_impact_col_fraction,
    _table_font_size,
    _table_header_font_size,
    _table_impact_col_index,
    _driver_influence_sentiment,
    FONT_REGULAR,
)


def _pdf_with_fonts() -> _ReportPDF:
    regular, bold, italic = _find_fonts()
    pdf = _ReportPDF(footer_title="test")
    pdf.set_margins(14, 16, 14)
    pdf.add_page()
    pdf.add_font(FONT_REGULAR, "", str(regular))
    pdf.add_font(FONT_REGULAR, "B", str(bold))
    pdf.add_font(FONT_REGULAR, "I", str(italic or regular))
    return pdf


def test_impact_col_width_matches_table1_reference():
    pdf = _pdf_with_fonts()
    body = _table_font_size(5)
    header = _table_header_font_size(body)
    ref = _reference_impact_col_fraction(pdf, font_size=body, header_font_size=header)

    table_profiles = [
        ["#", "Отрасль", "Влияние", "Обоснование"],
        ["Компания", "Зона", "Отрасль", "Новость", "Влияние"],
        ["Время", "Событие", "Тип", "Влияние", "На что влияет"],
    ]
    for headers in table_profiles:
        preset = _fixed_table_col_widths(headers)
        assert preset is not None
        aligned = _apply_reference_impact_col_width(pdf, headers, preset, ref)
        impact_j = _table_impact_col_index(headers)
        assert impact_j is not None
        assert abs(aligned[impact_j] - ref) < 0.001


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
