"""환율 관련 뉴스 수집.

배치에서 하루 한 번만 RSS 를 읽는다. 사용자 접속 시 크롤링하면 느려지고
언론사에서 차단당한다.

저작권: 기사 본문은 저장하지 않는다. 제목·출처·날짜·링크만 보관하고
본문은 원문 링크로 보낸다.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config

log = logging.getLogger(__name__)

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:                                     # pragma: no cover
    HAS_FEEDPARSER = False
    log.warning("feedparser 미설치 - 뉴스 수집을 건너뜁니다.")


# 언론사가 봇을 막거나 주소를 바꾸는 일이 잦다. 여러 개를 두고
# 실패한 피드는 조용히 건너뛴다.
FEEDS = [
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml"),
    ("한국경제", "https://www.hankyung.com/feed/economy"),
    ("매일경제 경제", "https://www.mk.co.kr/rss/30100041/"),
    ("이데일리 경제", "https://rss.edaily.co.kr/edaily_news.xml"),
]

# 제목에 이 중 하나라도 있어야 환율 관련으로 본다.
KEYWORDS = [
    "환율", "원화", "달러", "원/달러", "원달러", "외환",
    "연준", "Fed", "FOMC", "금통위", "기준금리",
    "무역수지", "경상수지", "외국인", "국채", "위안", "엔화",
]

MAX_ITEMS = 12
MAX_AGE_DAYS = 7
TIMEOUT_SEC = 10


def _clean(text: str) -> str:
    """HTML 태그와 공백을 정리한다."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _matches(title: str) -> bool:
    return any(k.lower() in title.lower() for k in KEYWORDS)


def collect() -> dict:
    """RSS 를 읽어 환율 관련 기사만 추린다.

    개별 피드가 실패해도 나머지로 계속 진행한다. 전부 실패하면
    빈 목록을 반환하되 배치를 중단시키지 않는다.
    """
    if not HAS_FEEDPARSER:
        return {"available": False, "reason": "feedparser 미설치", "items": []}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    items, ok_feeds, failed = [], [], []
    seen_titles: set[str] = set()

    for source, url in FEEDS:
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0 (compatible; FXDashboard/1.0)")
            entries = getattr(feed, "entries", [])
            if not entries:
                raise RuntimeError("항목 없음")

            count = 0
            for e in entries:
                title = _clean(getattr(e, "title", ""))
                link = getattr(e, "link", "")
                if not title or not link or not _matches(title):
                    continue

                # 같은 기사가 여러 매체에 실리는 경우가 많다.
                key = re.sub(r"[^가-힣a-zA-Z0-9]", "", title)[:40]
                if key in seen_titles:
                    continue
                seen_titles.add(key)

                published = _parse_date(e)
                if published and published < cutoff:
                    continue

                items.append({
                    # 저작권: 제목·출처·링크만. 본문은 저장하지 않는다.
                    "title": title[:150],
                    "source": source,
                    "link": link,
                    "published": (published.astimezone(ZoneInfo(config.TIMEZONE))
                                  .strftime("%Y-%m-%d %H:%M") if published else ""),
                    "_sort": published.timestamp() if published else 0,
                })
                count += 1

            ok_feeds.append(f"{source}({count})")
        except Exception as exc:
            log.warning("RSS 실패 [%s]: %s", source, exc)
            failed.append(source)

    items.sort(key=lambda x: x["_sort"], reverse=True)
    for it in items:
        it.pop("_sort", None)

    log.info("뉴스 수집: %d건 (성공 %s / 실패 %s)",
             len(items), ", ".join(ok_feeds) or "없음", ", ".join(failed) or "없음")

    return {
        "available": bool(items),
        "items": items[:MAX_ITEMS],
        "collected_at": now.astimezone(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d %H:%M"),
        "sources_ok": ok_feeds,
        "sources_failed": failed,
        "reason": "" if items else "조건에 맞는 기사를 찾지 못했습니다",
        "note": (
            "환율 관련 키워드가 제목에 포함된 기사만 모았습니다. "
            "기사와 환율 움직임 사이에 인과관계가 있다는 뜻은 아닙니다."
        ),
    }
