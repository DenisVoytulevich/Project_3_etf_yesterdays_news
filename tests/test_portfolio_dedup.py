# Тесты дедупликации §3.

from src.companies.context import TrackedCompany
from src.report.markdown_tables import finalize_portfolio_companies_news

_REQUIRED = ["IT / Technology", "Consumer Discretionary", "Telecom"]
_TRACKED = [
    TrackedCompany(
        name="NVIDIA Corporation",
        symbol="NVDA",
        sector="Information Technology",
        zone="Портфель",
        weight_pct=5.0,
    ),
    TrackedCompany(
        name="Microsoft Corporation",
        symbol="MSFT",
        sector="Information Technology",
        zone="Портфель",
        weight_pct=4.0,
    ),
    TrackedCompany(
        name="Micron Technology, Inc.",
        symbol="MU",
        sector="Information Technology",
        zone="Наблюдение",
    ),
]

_TABLE = """\
| Компания | Зона | Отрасль | Новость за вчера | Влияние |
|----------|------|---------|------------------|---------|
| NVIDIA Corporation | Портфель | Semiconductors | Новость A | +1 |
| NVIDIA Corporation | Наблюдение | Semiconductors | Новость B | +1 |
| Microsoft Corporation | Портфель | Technology | Claude GA без EU | -2 |
| Microsoft Corporation | Портфель | Technology | Frontier Company | +2 |
| Micron Technology, Inc. | Наблюдение | Semiconductors | Рост акций | +1 |
"""


def _company_names(table: str) -> list[str]:
    lines = [
        line
        for line in table.splitlines()
        if line.startswith("| ") and not line.startswith("| -")
    ]
    return [line.split("|")[1].strip() for line in lines[1:]]


def test_finalize_portfolio_merges_duplicate_companies():
    result = finalize_portfolio_companies_news(
        _TABLE,
        required_sectors=_REQUIRED,
        tracked_companies=_TRACKED,
    )
    names = _company_names(result)
    assert names.count("NVIDIA Corporation") == 1
    assert names.count("Microsoft Corporation") == 1
    assert len(names) == 3
    assert "Semiconductors" not in result
    assert "IT / Technology" in result
    assert "Портфель" in result
    assert "Новость A" in result and "Новость B" in result
    assert "Claude" in result and "Frontier" in result
    assert "-2" in result
