# Тесты дедупликации §2.

from src.report.markdown_tables import deduplicate_sector_ratings, ensure_sector_ratings_coverage

_REQUIRED = [
    "Дата центры",
    "Золотодобывающие компании",
    "Отросль ядерной энергетики",
    "Оборона",
    "IT / Technology",
    "Финансы",
    "Промышленность",
    "Энергетика",
    "Consumer Discretionary",
    "Telecom",
    "Здравоохранение",
    "Consumer Staples",
]

_REVISED_SECTOR_TABLE = """\
| # | Отрасль | Влияние | Обоснование |
|---|---------|---------|-------------|
| 1 | Авиакомпании | +2 | M&A easyJet |
| 2 | Оборона | +2 | Defense deals |
| 3 | Энергетика | +1 | Iraq pipelines |
| 4 | Потребительский сектор (дискреционные товары и услуги) | +1 | iPhone |
| 5 | Промышленность | +1 | EPC |
| 6 | Информационные технологии | +1 | Apple cycle |
| 7 | Телекоммуникации | +1 | Device upgrades |
| 8 | Финансы | 0 | Нет сигналов |
| 9 | Здравоохранение | 0 | Нет сигналов |
| 10 | Товары повседневного спроса | 0 | Нет сигналов |
| 11 | Дата‑центры | 0 | Нет сигналов |
| 12 | Золотодобывающие компании | 0 | Нет сигналов |
| 13 | Ядерная энергетика | 0 | Нет сигналов |
"""


def _sector_names(table: str) -> list[str]:
    lines = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| -")]
    return [line.split("|")[2].strip() for line in lines[1:]]


def test_deduplicate_merges_ru_en_sector_aliases():
    result = deduplicate_sector_ratings(_REVISED_SECTOR_TABLE, _REQUIRED)
    names = _sector_names(result)
    assert "Информационные технологии" not in names
    assert "IT / Technology" in names
    assert "Телекоммуникации" not in names
    assert "Telecom" in names
    assert "Товары повседневного спроса" not in names
    assert "Consumer Staples" in names
    assert "Дата‑центры" not in names
    assert "Дата центры" in names
    assert "Ядерная энергетика" in names
    assert "Отросль ядерной энергетики" not in names
    assert len(names) == len(set(names))


def test_deduplicate_merges_ru_variant_spellings():
    table = """\
| # | Отрасль | Влияние | Обоснование |
|---|---------|---------|-------------|
| 1 | Отросль ядерной энергетики | 0 | Нет сигналов |
| 2 | Ядерная энергетика | +1 | Новый контракт |
"""
    required = ["Отросль ядерной энергетики", "Энергетика"]
    result = deduplicate_sector_ratings(table, required)
    names = _sector_names(result)
    assert names == ["Ядерная энергетика"]
    assert "+1" in result


def test_coverage_does_not_add_duplicates_after_dedup():
    deduped = deduplicate_sector_ratings(_REVISED_SECTOR_TABLE, _REQUIRED)
    covered = ensure_sector_ratings_coverage(deduped, _REQUIRED)
    names = _sector_names(covered)
    assert "IT / Technology" in names
    assert "Информационные технологии" not in names
    assert len(names) == len({name.lower() for name in names})
