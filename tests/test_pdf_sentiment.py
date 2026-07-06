"""Тесты раскраски драйверов и ширины колонок в PDF."""

from src.report.pdf import (
    _ReportPDF,
    _apply_reference_impact_col_width,
    _apply_reference_index_col_width,
    _ensure_sector_rating_col_width,
    _find_fonts,
    _fixed_table_col_widths,
    _reference_impact_col_fraction,
    _reference_index_col_fraction,
    _REF_TABLE_BODY_FONT_SIZE,
    _REF_TABLE_HEADER_FONT_SIZE,
    _table_font_size,
    _table_header_font_size,
    _table_impact_col_index,
    _uniform_table_header_font_size,
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


def test_uniform_table_header_font_size():
    assert _uniform_table_header_font_size() == _REF_TABLE_HEADER_FONT_SIZE
    assert _uniform_table_header_font_size() == _table_header_font_size(_REF_TABLE_BODY_FONT_SIZE)
    assert _uniform_table_header_font_size() != _table_header_font_size(_table_font_size(4))


def test_impact_col_width_matches_table1_reference():
    pdf = _pdf_with_fonts()
    header = _uniform_table_header_font_size()
    ref = _reference_impact_col_fraction(
        pdf, font_size=_REF_TABLE_BODY_FONT_SIZE, header_font_size=header
    )

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


def test_sector_ratings_index_col_width_matches_table1_reference():
    pdf = _pdf_with_fonts()
    header = _uniform_table_header_font_size()
    body = _REF_TABLE_BODY_FONT_SIZE
    ref_index = _reference_index_col_fraction(
        pdf, font_size=body, header_font_size=header
    )

    headers = ["#", "Отрасль", "Влияние", "Обоснование"]
    preset = _fixed_table_col_widths(headers)
    assert preset is not None
    col_widths = _ensure_sector_rating_col_width(
        pdf, headers, preset, header_font_size=header, font_size=body
    )
    ref_impact = _reference_impact_col_fraction(
        pdf, font_size=body, header_font_size=header
    )
    col_widths = _apply_reference_impact_col_width(pdf, headers, col_widths, ref_impact)
    aligned = _apply_reference_index_col_width(pdf, headers, col_widths, ref_index)
    assert abs(aligned[0] - ref_index) < 0.001


def test_sector_ratings_impact_header_fits_at_uniform_size():
    pdf = _pdf_with_fonts()
    headers = ["#", "Отрасль", "Влияние", "Обоснование"]
    header = _uniform_table_header_font_size()
    ref = _reference_impact_col_fraction(
        pdf, font_size=_REF_TABLE_BODY_FONT_SIZE, header_font_size=header
    )
    preset = _fixed_table_col_widths(headers)
    assert preset is not None
    aligned = _apply_reference_impact_col_width(pdf, headers, preset, ref)
    impact_j = 2
    pdf.set_font(FONT_REGULAR, "B", header)
    needed = pdf.get_string_width("Влияние") + 5.0
    assert aligned[impact_j] * pdf.epw >= needed - 0.1

def test_top_market_news_table_detects_otrasl_column():
    from src.report.pdf import (
        MdTable,
        _is_top_market_news_table,
        _prepare_top_market_news_table,
        _top_news_event_groups,
        _top_news_merge_col_indices,
    )

    headers = ["#", "Событие", "Влияние", "Отрасль", "Драйвер сектора"]
    assert _is_top_market_news_table(headers)
    assert _top_news_merge_col_indices(headers) == (0, 1, 2)

    rows = [
        ["1", "OPEC+ одобрила рост добычи", "-3", "Energy", "Предложение нефти: рост"],
        ["1", "OPEC+ одобрила рост добычи", "-3", "Industry", "Цена нефти: снижение"],
        ["2", "easyJet сделка", "+2", "Airlines", "Топливо: снижение"],
    ]
    prepared = _prepare_top_market_news_table(MdTable(headers=headers, rows=rows))
    groups = _top_news_event_groups(prepared.rows, event_col=1)
    assert any(span > 1 for _, span in groups)


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


def test_top_news_cell_sentiment_splits_event_and_driver_colors():
    from src.report.pdf import _top_news_cell_sentiment

    headers = ["#", "Событие", "Влияние", "Сектор", "Драйвер сектора"]
    row = ["1", "OPEC+", "+2", "Energy", "Oil supply: growth"]
    event_sentiment = "positive"
    assert _top_news_cell_sentiment(headers, row, 2, event_sentiment) == "positive"
    assert _top_news_cell_sentiment(headers, row, 3, event_sentiment) == "negative"
    assert _top_news_cell_sentiment(headers, row, 4, event_sentiment) == "negative"


def test_english_product_cycle_accelerated_is_positive():
    assert _driver_influence_sentiment("Product cycle: accelerated") == "positive"


def test_english_fuel_lower_is_positive_for_sector():
    assert _driver_influence_sentiment("Fuel: lower") == "positive"


def test_english_export_capacity_expanding_negative_for_energy():
    assert _driver_influence_sentiment("Export capacity plans: expanding") == "negative"


def test_english_contract_pipeline_stronger_is_positive():
    assert _driver_influence_sentiment("Contract pipeline: stronger") == "positive"


def test_english_cautiously_improving_is_positive():
    assert (
        _driver_influence_sentiment(
            "EPC demand outlook: cautiously improving (study phase)"
        )
        == "positive"
    )
