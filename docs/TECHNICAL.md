# Техническая документация — постобработка и качество отчёта

Документ фиксирует **детерминированный слой** после LLM-агентов: нормализация таблиц, дедупликация и раскраска PDF.  
Агенты формируют черновик; код в `Consistency Validator` и `pdf.py` приводит результат к единым правилам.

Связанные файлы:

| Область | Код | Тесты |
|---------|-----|-------|
| §2 отрасли | `src/report/markdown_tables.py`, `src/structure/labels.py` | `tests/test_sector_dedup.py`, `tests/test_sector_interest.py` |
| §3 компании | `src/report/markdown_tables.py`, `src/companies/context.py` | `tests/test_portfolio_dedup.py` |
| §1 PDF-цвет | `src/report/pdf.py` | `tests/test_pdf_sentiment.py` |
| Валидатор | `src/pipeline/stages/consistency.py` | `tests/test_consistency.py` |

Чекпоинты прогона: `data/pipeline/<run_id>/` (00–09).

---

## 1. Мультиагентный пайплайн (контекст)

```
Focus → News → Entity Extractor → Theme Normalizer → Analyst
  → QA-1 Editor → QA-2 Analytics → Revision → Consistency Validator → Renderer
```

**Важно:** сбои «дублей», «смеси EN/RU», «серых ячеек» часто выглядят как «агент не работает», но агенты **отрабатывают** (есть чекпоинты). Проблема — расхождение вывода LLM с словарём портфеля; её закрывает постобработка.

### Промпты (июль 2026)

- **Analyst** (`prompts/analyst.md`): в §2 названия отраслей **дословно** из «Отраслей интереса»; в §3 — **одна строка на компанию**.
- **QA-1** (`prompts/qa_editor.md`): получает `interest_sectors_context`; **не** предлагает перевод `Telecom` → «Телекоммуникации» и т.п.
- **Revision** (`prompts/revision_agent.md`): тот же эталон отраслей; не переименовывает §2 произвольно.

QA-1 и Revision вызываются с `focus.interest_sectors_context` (`src/pipeline/stages/qa_editor.py`, `revision.py`).

---

## 2. §2 — Рейтинг отраслей

### Проблема

- Analyst / Revision пишут отрасли на **английском** или **свободном русском** (`Информационные технологии`, `Телекоммуникации`).
- В Google Sheets эталон другой (`IT / Technology`, `Telecom`, `Дата центры`).
- `ensure_sector_ratings_coverage` не находила совпадение и **добавляла вторую строку** с именем из портфеля → «дубль на дубле» EN+RU.

### Решение: `finalize_sector_ratings()`

Файл: `src/report/markdown_tables.py`

Порядок:

1. `deduplicate_sector_ratings` — слияние синонимов (RU/EN, опечатки).
2. `_canonicalize_sector_table_names` — имена из словаря портфеля.
3. `ensure_sector_ratings_coverage` — добавить пропущенные обязательные отрасли.
4. Повтор dedupe + канонизация.

Вызывается из `run_consistency_validator()` (`src/pipeline/stages/consistency.py`).

### Словарь отраслей

Файл: `src/structure/labels.py`

| Механизм | Назначение |
|----------|------------|
| `SECTOR_LABELS` | GICS/англ. метки → отображаемое имя (`Technology` → `IT / Technology`, `Telecommunications` → `Telecom`) |
| `SECTOR_ALIASES` | Синонимы для нечёткого сопоставления (RU/EN, в т.ч. `telecommunications`, `информационные технологии`) |
| `SECTOR_TYPO_FIXES` | Опечатки → канон (`Отросль ядерной энергетики` → `Ядерная энергетика`; `Дата‑центры` → `Дата центры`) |
| `sector_matches()` | Совпадение двух строк отрасли через алиасы |
| `canonical_sector_name()` | Итоговое имя для §2 из списка `screening_sectors` |
| `normalize_required_sectors()` | Список обязательных отраслей без дублей при сборе из Sheets |

Сбор отраслей: `src/sectors/interest.py` — `_add_sector()` дедуплицирует через `sector_matches`, в конце `collect_screening_sectors()` вызывает `normalize_required_sectors()`.

### Правило для контента

**В §2 в PDF/MD должны быть имена из портфеля** (как в `00_focus.json` → `screening_sectors`), не перевод QA-редактора.

---

## 3. §3 — Новости по компаниям

### Проблема

- Одна бумага **дважды**: `NVIDIA Corporation` в Портфеле и Наблюдении; `Microsoft` — две новости в одной зоне.
- Отрасли в GICS-англицизмах (`Semiconductors`, `Technology`) вместо имён из списка компаний.

### Решение: `finalize_portfolio_companies_news()`

Файл: `src/report/markdown_tables.py`

1. Ключ компании: `company_identity_key()` — `NVIDIA` / `NVIDIA Corporation` → один ключ (`src/companies/context.py`).
2. Справочник: `build_company_lookup()` — портфель важнее watchlist.
3. Для каждой строки: каноническое **имя**, **зона**, **отрасль** из `TrackedCompany`.
4. Дубли **сливаются**:
   - зона: приоритет `Портфель` > `Наблюдение`;
   - влияние: строка с большим \|impact\|;
   - при равном \|impact\| и разном знаке для риска — сохраняется более консервативная оценка;
   - новости объединяются через `;`.

Вызывается из `run_consistency_validator()` после `finalize_sector_ratings()`.

---

## 4. §1 — Раскраска PDF (двухуровневая система)

**Не путать** с «одним цветом по Влиянию на всю строку» — это было ошибочное упрощение; откатано.

Коммит-источник логики: `66f66a4` — *Color §1 PDF rows by sector driver pressure, not event strength.*

Файл: `src/report/pdf.py`

### Правила

| Колонки | Цвет |
|---------|------|
| `#`, `Событие`, `Влияние` (объединённые ячейки события) | По **знаку «Влияния»** события: `+N` зелёный, `−N` красный, `0` серый (`impact_sentiment`) |
| `Сектор`, `Драйвер` (подстроки по отраслям) | По **вектору давления на отрасль** — разбор текста драйвера (`_driver_influence_sentiment`) |

Функция точки входа: `_top_news_cell_sentiment()`.

### Примеры смысла

- Событие **+1**, драйвер `Oil supply: growth` → колонки события зелёные, сектор/драйвер **красные** (рост предложения — негатив для Energy).
- Событие **+2**, драйвер `Fuel: lower` / `Топливо: снижение` → сектор/драйвер **зелёные** (снижение издержек — позитив для авиакомпаний).

### Парсер драйверов

Формат в промпте Analyst: `{драйвер}: {изменение}` (часто **на английском** после Revision).

`_driver_clause_sentiment()` / `_driver_change_direction()` поддерживают **RU + EN**:

- рост: `рост`, `accelerated`, `higher`, `expanding`, `improving`, `stronger`, …
- снижение: `снижение`, `lower`, `declining`, `pressure down`, …
- издержки: `fuel`, `logistics`, `cost` — снижение = позитив для сектора
- предложение/добыча: `supply`, `export capacity` — рост = негатив для сырья
- спец-кейсы: `margin expansion`, `valuation support`, `cautiously improving` (позитив, не путать с голым `cautious`)

Маркеры: `_DRIVER_COST_MARKERS`, `_DRIVER_SUPPLY_MARKERS`, `_DRIVER_GROWTH_POSITIVE_MARKERS`, `_DRIVER_NEGATIVE_WHEN_RISING`, `_DRIVER_COMMODITY_PRICE_MARKERS`.

### Детекция таблицы §1

`_is_top_market_news_table()` — 5 колонок: `# | Событие | Сила/Влияние | Сектор/Отрасль | Драйвер*`.  
Объединение ячеек: `_top_news_merge_col_indices()` → `(0, 1, 2)`.

---

## 5. Consistency Validator

Файл: `src/pipeline/stages/consistency.py`

**До публикации** мутирует секции (не только проверяет):

```python
required_sectors = normalize_required_sectors(focus.screening_sectors)
sections["sector_ratings"] = finalize_sector_ratings(...)
sections["portfolio_companies_news"] = finalize_portfolio_companies_news(...)
```

Затем проверки: пустые секции, диапазон ±5, дубли отраслей (`sector_matches`), дубли компаний (`company_identity_key`).

Замечания пишутся в лог; отчёт **всё равно рендерится** с исправленными таблицами.

---

## 6. Отладка

| Симптом | Где смотреть |
|---------|-------------|
| Дубли отраслей EN/RU | `08_validated.json` → `sector_ratings`; лог `§2: удалены дубли` / `добавлены пропущенные` |
| Дубли компаний | `08_validated.json` → `portfolio_companies_news`; лог `§3: удалены дубли` |
| QA переводит отрасли | `05_qa_editor.json` — замечания; убедиться, что в промпт уходит `interest_sectors_context` |
| Серые сектор/драйвер в §1 | английский драйвер без маркеров → дописать в `_driver_change_direction` / `SECTOR_*` или проверить формат `Driver: change` |
| Эталон отраслей | `data/pipeline/<run_id>/00_focus.json` → `screening_sectors` |

Пересборка PDF без полного пайплайна:

```bash
python regenerate_report_pdf.py   # если есть готовый .md
python verify_pdf_layout.py     # preview из templates/example.md
```

Тесты:

```bash
python -m pytest tests/test_sector_dedup.py tests/test_portfolio_dedup.py tests/test_pdf_sentiment.py tests/test_consistency.py -q
```

---

## 7. Хронология изменений (2026-07-06)

1. **§2:** `finalize_sector_ratings`, расширение `SECTOR_ALIASES`, `SECTOR_TYPO_FIXES`, `normalize_required_sectors`.
2. **Агенты:** `interest_sectors_context` в QA-1 и Revision; запрет произвольного перевода §2.
3. **§3:** `finalize_portfolio_companies_news`, `company_identity_key`, `build_company_lookup`.
4. **§1 PDF:** восстановлена двухуровневая раскраска; EN-парсинг драйверов (вместо ошибочного «один цвет по Влиянию»).

При добавлении новых синонимов отраслей или EN-маркеров драйверов — **сначала тест** в `tests/`, затем правка `labels.py` / `pdf.py`.
