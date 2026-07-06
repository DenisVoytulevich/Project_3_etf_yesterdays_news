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

# Известные опечатки и устаревшие формулировки → единое имя в отчёте.
SECTOR_TYPO_FIXES: dict[str, str] = {
    "отросль ядерной энергетики": "Ядерная энергетика",
    "отрасль ядерной энергетики": "Ядерная энергетика",
}

# Синонимы отраслей для сопоставления (нижний регистр).
SECTOR_ALIASES: dict[str, list[str]] = {
    "дата центры": [
        "data center",
        "data centers",
        "дата-центр",
        "дата-центры",
        "дата‑центры",
        "цод",
        "цоды",
    ],
    "финансы": ["financial", "financials", "financial services", "банк", "bank"],
    "it / technology": [
        "technology",
        "information technology",
        "tech",
        "semiconductor",
        "информационные технологии",
        "ит и технологии",
        "технологии",
    ],
    "промышленность": ["industrial", "industrials"],
    "энергетика": ["energy", "oil", "gas"],
    "здравоохранение": ["health", "healthcare"],
    "недвижимость": ["real estate", "reit"],
    "телеком": ["telecom", "communication", "телекоммуникации", "communication services"],
    "consumer discretionary": [
        "consumer cyclical",
        "потребительский сектор",
        "дискреционный сектор",
        "дискреционные товары",
        "потребительский сектор (дискреционные товары и услуги)",
    ],
    "consumer staples": [
        "consumer defensive",
        "товары повседневного спроса",
        "основные потребительские товары",
    ],
    "авиакомпании": ["airlines", "авиа", "авиаперевозки"],
    "ядерная энергетика": [
        "nuclear",
        "nuclear energy",
        "отрасль ядерной энергетики",
        "отросль ядерной энергетики",
    ],
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
    text = sector.strip().lower()
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", text)
    text = re.sub(r"[-\s]+", " ", text).strip()
    return text


def sector_aliases(sector: str) -> list[str]:
    """Варианты написания отрасли для нечёткого сопоставления."""
    key = _normalize_sector_key(sector)
    aliases: list[str] = [key]

    def _add(value: str) -> None:
        norm = _normalize_sector_key(value)
        if norm and norm not in aliases:
            aliases.append(norm)

    for alias in SECTOR_ALIASES.get(key, []):
        _add(alias)

    for canonical, alias_list in SECTOR_ALIASES.items():
        canonical_key = _normalize_sector_key(canonical)
        alias_keys = {_normalize_sector_key(alias) for alias in alias_list}
        if key == canonical_key or key in alias_keys:
            _add(canonical)
            for alias in alias_list:
                _add(alias)

    labeled = sector_label(sector.strip())
    _add(labeled)
    for alias in SECTOR_ALIASES.get(_normalize_sector_key(labeled), []):
        _add(alias)

    for label, mapped in SECTOR_LABELS.items():
        if _normalize_sector_key(label) == key or _normalize_sector_key(mapped) == key:
            _add(label)
            _add(mapped)

    return aliases


def sector_identity_key(sector: str) -> str:
    """Нормализованный ключ отрасли для дедупликации (с учётом синонимов и опечаток)."""
    preferred = preferred_sector_display_name(sector)
    return _normalize_sector_key(preferred)


def preferred_sector_display_name(sector: str) -> str:
    """Единое отображаемое имя: исправляет опечатки и устаревшие формулировки."""
    stripped = sector.strip()
    if not stripped or stripped == "—":
        return stripped
    fixed = SECTOR_TYPO_FIXES.get(_normalize_sector_key(stripped))
    if fixed:
        return fixed
    labeled = sector_label(stripped)
    fixed = SECTOR_TYPO_FIXES.get(_normalize_sector_key(labeled))
    if fixed:
        return fixed
    return labeled


def canonical_sector_name(sector: str, required_sectors: list[str]) -> str:
    """Каноническое имя отрасли: синонимы + исправление опечаток из списка обязательных."""
    preferred = preferred_sector_display_name(sector)
    for required in required_sectors:
        if sector_matches(sector, required):
            return preferred_sector_display_name(required)
    return preferred


def sector_matches(table_sector: str, required: str) -> bool:
    """Сопоставление отрасли из таблицы §2 с обязательной отраслью (синонимы, составные ячейки)."""
    table = _normalize_sector_key(table_sector)
    if not table or table == "—":
        return False
    req_key = _normalize_sector_key(required)
    if table == req_key:
        return True
    req_aliases = {_normalize_sector_key(alias) for alias in sector_aliases(required)}
    table_aliases = {_normalize_sector_key(alias) for alias in sector_aliases(table_sector)}
    if req_aliases & table_aliases:
        return True
    return False

