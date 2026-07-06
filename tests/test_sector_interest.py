# Тесты дедупликации отраслей при сборе из Portfel/Watchlist.

from src.data.models import InterestZoneItem, PortfolioAnalytics, SectorInterest
from src.sectors.interest import collect_screening_sectors


def test_screening_sectors_merge_nuclear_typo_and_canonical():
    analytics = PortfolioAnalytics(
        sector_interests=[
            SectorInterest(sector="Отросль ядерной энергетики"),
        ],
        interest_zone=[
            InterestZoneItem(sector="Ядерная энергетика", isin="", name=""),
        ],
    )
    sectors = collect_screening_sectors(analytics, structure=None)
    assert sectors == ["Ядерная энергетика"]
