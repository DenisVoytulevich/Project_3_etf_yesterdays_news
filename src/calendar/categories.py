from __future__ import annotations

import re
from dataclasses import dataclass

# Порядок важен: более специфичные категории проверяются раньше.
MACRO_CATEGORIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "central_banks",
        "Решения центральных банков",
        (
            "fomc", "fed ", "federal reserve", "ecb", "european central bank",
            "boe ", "bank of england", "boj ", "bank of japan", "pboc",
            "interest rate", "rate decision", "monetary policy", "policy rate",
            "central bank", "bundesbank", "rba ", "boc ", "snb ",
            "powell", "lagarde", "ставк", "цб ", "ключев",
        ),
    ),
    (
        "sanctions",
        "Санкции",
        (
            "sanction", "embargo", "blacklist", "export ban", "import ban",
            "санкц", "эмбарго",
        ),
    ),
    (
        "geopolitics",
        "Геополитика",
        (
            "geopolit", "ukraine", "russia", "taiwan", "china-us", "nato",
            "middle east", "israel", "gaza", "iran", "war ", "conflict",
            "military", "ceasefire", "invasion", "геополит", "войн",
            "конфликт", "нато",
        ),
    ),
    (
        "inflation",
        "Инфляция",
        (
            "cpi", "hicp", "ppi", "pce", "inflation", "price index",
            "core inflation", "consumer price", "producer price",
            "инфляц", "ипц",
        ),
    ),
    (
        "labor",
        "Рынок труда",
        (
            "employment", "payroll", "jobless", "unemployment", "jolts",
            "nonfarm", "non-farm", "nfp", "labor", "labour", "wage",
            "job openings", "jobless claims", "adp employment",
            "занятост", "безработ", "рынок труда", "зарплат",
        ),
    ),
    (
        "pmi",
        "PMI",
        (
            "pmi", "purchasing managers", "ism manufacturing", "ism services",
            "tankan", "composite pmi", "flash pmi",
        ),
    ),
    (
        "gdp",
        "ВВП",
        (
            "gdp", "gross domestic", "economic growth", "ввп",
        ),
    ),
    (
        "commodities",
        "Сырьевые рынки",
        (
            "crude oil", "oil inventory", "api weekly", "opec", "natural gas",
            "gold ", "copper", "commodity", "commodities", "wheat", "corn",
            "energy stock", "нефт", "сырь", "газ ", "золот",
        ),
    ),
    (
        "government",
        "Решения правительств",
        (
            "budget", "fiscal", "stimulus", "election", "parliament",
            "congress", "government", "cabinet", "tariff", "trade deal",
            "spending bill", "правительств", "бюджет", "тариф", "фискал",
        ),
    ),
)

CATEGORY_LABELS = {cat_id: label for cat_id, label, _ in MACRO_CATEGORIES}
MANDATORY_CATEGORY_IDS = tuple(cat_id for cat_id, _, _ in MACRO_CATEGORIES)


@dataclass
class MacroNewsItem:
    title: str
    summary: str
    category: str
    date_str: str


def classify_macro_text(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text.lower())
    for cat_id, _, keywords in MACRO_CATEGORIES:
        for keyword in keywords:
            if keyword in normalized:
                return cat_id
    return None


def category_label(category_id: str | None) -> str:
    if not category_id:
        return "Прочее"
    return CATEGORY_LABELS.get(category_id, "Прочее")


def select_diverse_events(events, *, limit: int = 10):
    """Выбирает события с покрытием обязательных категорий."""
    importance_rank = {"высокая": 3, "средняя": 2, "низкая": 1}
    by_category: dict[str, list] = {cat_id: [] for cat_id in MANDATORY_CATEGORY_IDS}
    uncategorized: list = []

    for event in events:
        cat = classify_macro_text(event.name) or "other"
        if cat in by_category:
            by_category[cat].append(event)
        else:
            uncategorized.append(event)

    for items in by_category.values():
        items.sort(
            key=lambda e: (-importance_rank.get(e.importance, 0), e.event_at),
        )
    uncategorized.sort(
        key=lambda e: (-importance_rank.get(e.importance, 0), e.event_at),
    )

    selected: list = []
    seen_names: set[str] = set()

    def _add(event) -> bool:
        key = event.name.strip().lower()
        if key in seen_names:
            return False
        seen_names.add(key)
        selected.append(event)
        return True

    for cat_id in MANDATORY_CATEGORY_IDS:
        if by_category[cat_id]:
            _add(by_category[cat_id][0])

    pool = [
        e
        for cat_id in MANDATORY_CATEGORY_IDS
        for e in by_category[cat_id][1:]
    ] + uncategorized
    pool.sort(key=lambda e: (-importance_rank.get(e.importance, 0), e.event_at))
    for event in pool:
        if len(selected) >= limit:
            break
        _add(event)

    selected.sort(key=lambda e: e.event_at)
    return selected[:limit]


def extract_macro_news(news_items, *, limit_per_category: int = 3) -> list[MacroNewsItem]:
    """Геополитика, санкции и решения правительств — из новостей (не в календаре)."""
    news_only_categories = {"geopolitics", "sanctions", "government"}
    found: dict[str, list[MacroNewsItem]] = {cat: [] for cat in news_only_categories}

    for item in news_items:
        text = f"{item.title} {item.summary}"
        cat = classify_macro_text(text)
        if cat not in news_only_categories:
            continue
        date_str = item.published.strftime("%d.%m") if item.published else "—"
        macro_item = MacroNewsItem(
            title=item.title,
            summary=item.summary[:200],
            category=cat,
            date_str=date_str,
        )
        titles = {m.title for m in found[cat]}
        if macro_item.title not in titles and len(found[cat]) < limit_per_category:
            found[cat].append(macro_item)

    result: list[MacroNewsItem] = []
    for cat_id in ("geopolitics", "sanctions", "government"):
        result.extend(found[cat_id])
    return result


def format_macro_news_for_prompt(news_items: list, *, limit: int = 25) -> str:
    """Макро-релевантные новости из всех приоритетов для промпта §5.1."""
    if not news_items:
        return "_Макро-релевантных новостей не найдено_"

    matched: list[tuple] = []
    seen_titles: set[str] = set()
    for item in news_items:
        cat = classify_macro_text(f"{item.title} {item.summary}")
        if not cat or item.title in seen_titles:
            continue
        seen_titles.add(item.title)
        matched.append((item, cat))

    if not matched:
        return "_Макро-релевантных новостей не найдено_"

    lines = [f"Макро-новости ({min(len(matched), limit)} из {len(matched)}):"]
    for item, cat in matched[:limit]:
        date_str = item.published.strftime("%d.%m") if item.published else "—"
        lines.append(
            f"- **{date_str}** | {CATEGORY_LABELS[cat]} | [{item.source}] {item.title}"
        )
        if item.summary:
            lines.append(f"  {item.summary[:200]}")
    return "\n".join(lines)
