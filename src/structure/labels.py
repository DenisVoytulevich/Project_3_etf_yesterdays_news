"""Метки, синонимы и ключевые слова отраслей для сопоставления с ETF."""

from __future__ import annotations

import re

SECTOR_LABELS: dict[str, str] = {
    "Technology": "IT / Technology",
    "Information Technology": "IT / Technology",
    "Financials": "Финансы",
    "Financial Services": "Финансы",
    "Basic Materials": "Сырьё",
    "Industrials": "Промышленность",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Discretionary": "Consumer Discretionary",
    "Communication Services": "Telecom",
    "Energy": "Энергетика",
    "Healthcare": "Здравоохранение",
    "Consumer Defensive": "Consumer Staples",
    "Utilities": "Коммунальные услуги",
    "Real Estate": "Недвижимость",
    "Defense": "Оборона",
    "Aerospace & Defense": "Оборона",
    "Aerospace and Defense": "Оборона",
    "Data Centers": "Дата центры",
    "Data Center": "Дата центры",
    "Data Center REITs": "Дата центры",
}

# Синонимы отраслей для сопоставления (нижний регистр).
SECTOR_ALIASES: dict[str, list[str]] = {
    "дата центры": ["data center", "data centers", "дата-центр", "дата-центры"],
    "финансы": ["financial", "financials", "financial services", "банк", "bank"],
    "it / technology": ["technology", "information technology", "tech", "semiconductor"],
    "промышленность": ["industrial", "industrials"],
    "энергетика": ["energy", "oil", "gas"],
    "здравоохранение": ["health", "healthcare"],
    "недвижимость": ["real estate", "reit"],
    "телеком": ["telecom", "communication"],
    "сырьё": ["materials", "basic materials", "mining"],
    "золотодобывающие компании": [
        "gold",
        "gold mining",
        "gold miners",
        "золото",
        "золотодобыча",
        "золотодоб",
    ],
    "медедобывающие компании": [
        "copper",
        "mining",
        "freeport",
        "bhp",
        "rio tinto",
        "antofagasta",
        "southern copper",
        "медь",
        "медедобыча",
    ],
    "оборона": ["defense", "aerospace", "defence", "оборонка", "defen"],
    "gamedev": [
        "game",
        "gaming",
        "video game",
        "videogame",
        "interactive media",
        "entertainment",
        "communication services",
        "software",
    ],
    "игры": ["game", "gaming", "gamedev", "video game"],
    "игровая": ["game", "gaming", "gamedev"],
}

# Тематические отрасли по названию/тикеру ETF (GICS часто даёт «Industrials» вместо «Defense»).
_ETF_THEME_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"defen[cs]e|оборон|aerospace.{0,24}defen|defen.{0,24}aerospace",
            re.IGNORECASE,
        ),
        "Оборона",
    ),
    (re.compile(r"semiconductor|полупровод", re.IGNORECASE), "Полупроводники"),
    (re.compile(r"gold|золот", re.IGNORECASE), "Золотодобывающие компании"),
    (re.compile(r"nuclear|ядерн", re.IGNORECASE), "Ядерная энергетика"),
    (re.compile(r"data\s*cent", re.IGNORECASE), "Дата центры"),
]


def infer_etf_theme_sectors(name: str, ticker: str = "") -> list[str]:
    """Тематическая отрасль ETF по названию (DFEN/DFND → Оборона и т.п.)."""
    text = f"{name} {ticker}".strip()
    if not text:
        return []
    sectors: list[str] = []
    seen: set[str] = set()
    for pattern, sector in _ETF_THEME_RULES:
        if not pattern.search(text):
            continue
        key = sector.lower()
        if key in seen:
            continue
        seen.add(key)
        sectors.append(sector)
    return sectors

# Ключевые слова в названии бумаги (если отрасль не совпала с сектором ETF).
SECTOR_HOLDING_KEYWORDS: dict[str, list[str]] = {
    "золотодобывающие компании": [
        "gold",
        "barrick",
        "newmont",
        "agnico",
        "kinross",
        "franco-nevada",
        "gold fields",
        "polyus",
        "yamana",
        "anglogold",
    ],
    "дата центры": [
        "equinix",
        "digital realty",
        "iron mountain",
        "cyrusone",
        "switch",
    ],
    "полупроводники": [
        "nvidia",
        "tsmc",
        "asml",
        "amd",
        "micron",
        "intel",
        "qualcomm",
        "broadcom",
    ],
    "gamedev": [
        "electronic arts",
        "activision",
        "blizzard",
        "take-two",
        "take two",
        "rockstar",
        "ubisoft",
        "nintendo",
        "roblox",
        "unity software",
        "unity ",
        "cd projekt",
        "capcom",
        "square enix",
        "bandai namco",
        "bandai",
        "konami",
        "zynga",
        "playtika",
        "embracer",
        "paradox interactive",
        "paradox",
        "ncsoft",
        "nexon",
        "epic games",
        "supercell",
        "netease",
        "fromsoftware",
        "gameloft",
        "scopely",
    ],
}


def _derived_sector_keywords(sector: str) -> list[str]:
    """Токены из названия отрасли — для динамических строк Watchlist без ручного справочника."""
    key = sector.strip().lower()
    tokens: set[str] = set()
    for part in re.split(r"[\s/,&_-]+", key):
        part = part.strip()
        if len(part) >= 3:
            tokens.add(part)
    if "game" in key:
        tokens.update(["game", "gaming", "videogame"])
    return sorted(tokens)


def holding_keywords_for_sector(sector: str) -> list[str]:
    key = sector.strip().lower()
    explicit: list[str] = []
    if key in SECTOR_HOLDING_KEYWORDS:
        explicit = list(SECTOR_HOLDING_KEYWORDS[key])
    else:
        for label, keywords in SECTOR_HOLDING_KEYWORDS.items():
            if label in key or key in label:
                explicit = list(keywords)
                break
    derived = _derived_sector_keywords(sector)
    merged: list[str] = []
    seen: set[str] = set()
    for word in explicit + derived:
        w = word.strip().lower()
        if w and w not in seen:
            seen.add(w)
            merged.append(w)
    return merged


def sector_label(name: str) -> str:
    return SECTOR_LABELS.get(name, name)


def _normalize_sector_key(sector: str) -> str:
    return sector.strip().lower()


def sector_aliases(sector: str) -> list[str]:
    """Варианты написания отрасли для нечёткого сопоставления."""
    key = _normalize_sector_key(sector)
    aliases = [key, sector.strip().lower()]
    for alias in SECTOR_ALIASES.get(key, []):
        if alias not in aliases:
            aliases.append(alias)
    labeled = sector_label(sector.strip())
    labeled_key = _normalize_sector_key(labeled)
    if labeled_key not in aliases:
        aliases.append(labeled_key)
    return aliases


def sector_matches(table_sector: str, required: str) -> bool:
    """Сопоставление отрасли из таблицы §2 с обязательной отраслью (синонимы, составные ячейки)."""
    table = _normalize_sector_key(table_sector)
    if not table or table == "—":
        return False
    req_key = _normalize_sector_key(required)
    if table == req_key:
        return True
    req_aliases = set(sector_aliases(required))
    table_aliases = set(sector_aliases(table_sector))
    if req_aliases & table_aliases:
        return True
    if req_key in table or table in req_key:
        return True
    return False

