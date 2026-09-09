"""조지아 현지 언론의 제목·발행일·원문 링크. 본문 복제 없음."""
import calendar
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

DIRECT = re.compile(r"\blari\b|exchange.rate|currenc|forex|monetary|refinanc|interest.rate", re.I)
RELATED = re.compile(r"inflation|remittance|touris|\bfdi\b|foreign.direct.invest|trade.balance|reserves|macroeconomic", re.I)


def eligible(title, link, published, host, now):
    return (urlparse(link).scheme == "https" and urlparse(link).hostname == host
            and bool(DIRECT.search(title) or RELATED.search(title))
            and now - timedelta(days=30) <= published <= now)


def collect():
    now = datetime.now(timezone.utc)
    items, states, seen = [], [], set()
    def add(title, link, published, name, host):
        title = BeautifulSoup(title, "html.parser").get_text(" ", strip=True)
        if not eligible(title, link, published, host, now) or link in seen:
            return
        seen.add(link)
        items.append({"title": title[:220], "link": link, "source": name,
                      "published": published.strftime("%Y-%m-%d"),
                      "category": "환율·통화정책" if DIRECT.search(title) else "관련 경제",
                      "timestamp": published.timestamp()})
    try:
        r = requests.get("https://civil.ge/feed", timeout=(10, 20))
        r.raise_for_status()
        entries = feedparser.parse(r.content).entries
        if not entries:
            raise ValueError("RSS 항목 없음")
        for e in entries:
            date = e.get("published_parsed")
            if date:
                published = datetime.fromtimestamp(calendar.timegm(date), timezone.utc)
                add(e.get("title", ""), e.get("link", ""), published, "Civil Georgia", "civil.ge")
        states.append({"source": "Civil Georgia", "status": "수집 성공"})
    except Exception as e:
        states.append({"source": "Civil Georgia", "status": f"수집 실패: {str(e)[:90]}"})
    # Georgia Today disables RSS. Parse the public newspaper listing instead.
    try:
        for page in ("https://georgiatoday.ge/category/business/", "https://georgiatoday.ge/category/business/page/2/"):
            r = requests.get(page, timeout=(10, 20))
            r.raise_for_status()
            articles = BeautifulSoup(r.text, "html.parser").select("article")
            if not articles:
                raise ValueError("기사 목록 없음")
            for article in articles:
                title = article.select_one("h3 a")
                date = article.select_one(".jeg_meta_date")
                if title and date:
                    try:
                        published = datetime.strptime(date.get_text(" ", strip=True), "%B %d, %Y").replace(tzinfo=timezone.utc)
                        add(title.get_text(" ", strip=True), title.get("href", ""), published, "Georgia Today", "georgiatoday.ge")
                    except ValueError:
                        continue
        states.append({"source": "Georgia Today", "status": "수집 성공"})
    except Exception as e:
        states.append({"source": "Georgia Today", "status": f"수집 실패: {str(e)[:90]}"})
    items.sort(key=lambda item: item["timestamp"], reverse=True)
    return {"available": bool(items), "items": items[:16], "sources": states,
            "collected_at": now.strftime("%Y-%m-%d %H:%M UTC"), "window_days": 30}

