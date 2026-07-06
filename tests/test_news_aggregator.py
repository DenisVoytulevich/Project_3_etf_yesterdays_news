from src.news.aggregator import _rss_url_for_yesterday


def test_google_news_rss_adds_yesterday_after_clause():
    source = {
        "name": "Reuters Business",
        "url": "https://news.google.com/rss/search?q=site:reuters.com+business&hl=en-US",
    }
    url = _rss_url_for_yesterday(source, "Europe/Warsaw")
    assert "after:" in url
    assert "site:reuters.com+business+after:" in url


def test_non_google_rss_url_unchanged():
    source = {
        "name": "Yahoo Finance",
        "url": "https://finance.yahoo.com/news/rssindex",
    }
    assert _rss_url_for_yesterday(source, "Europe/Warsaw") == source["url"]
