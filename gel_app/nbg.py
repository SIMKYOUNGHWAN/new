"""NBG(조지아 국립은행) 환율 수집.

NBG API 는 **날짜 하나당 한 번**만 조회할 수 있다. 3년치를 매번 받으면
750회 호출이 되어 배치가 느려지고 차단당한다. 그래서 받은 값을 CSV 에
캐시해 두고 빠진 날짜만 증분으로 채운다.

엔드포인트:
    {base}/{lang}/json/?currencies=USD&date=YYYY-MM-DD

응답(배열의 첫 원소):
    {"date": "...", "currencies": [
        {"code": "USD", "quantity": 1, "rate": 2.67, "diff": 0.01, ...}]}

주의: `quantity` 는 통화마다 다르다. 예를 들어 엔화는 100엔당 가격으로
나오므로 rate 를 quantity 로 나눠야 1단위 가격이 된다. 이걸 놓치면
그래프가 100배 틀어진다.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import pandas as pd
import requests

from . import config

log = logging.getLogger(__name__)

TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FXDashboard/1.0)"}


# ---------------------------------------------------------------- 단건 조회
def fetch_day(day: date, currencies: list[str]) -> dict[str, float]:
    """하루치 환율을 {통화코드: 1단위당 라리} 로 반환한다."""
    url = f"{config.NBG_BASE}/en/json/"
    params = {"currencies": ",".join(currencies), "date": day.isoformat()}

    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    if not payload:
        return {}

    out: dict[str, float] = {}
    for item in payload[0].get("currencies", []):
        code = item.get("code")
        rate = item.get("rate")
        qty = item.get("quantity") or 1
        if code and rate is not None:
            # quantity 로 나눠 1단위 가격으로 정규화한다.
            out[code] = float(rate) / float(qty)
    return out


# ---------------------------------------------------------------- 캐시
def load_cache() -> pd.DataFrame:
    if not config.RATES_CACHE.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(config.RATES_CACHE, parse_dates=["date"])
        return df.set_index("date").sort_index()
    except Exception as exc:
        log.error("환율 캐시 읽기 실패, 새로 시작합니다: %s", exc)
        return pd.DataFrame()


def save_cache(df: pd.DataFrame) -> None:
    tmp = config.RATES_CACHE.with_suffix(".tmp")
    df.sort_index().to_csv(tmp, index_label="date")
    tmp.replace(config.RATES_CACHE)


# ---------------------------------------------------------------- 증분 수집
def update_rates(currencies: list[str] | None = None,
                 years: int | None = None) -> pd.DataFrame:
    """캐시에 없는 날짜만 채워서 전체 시계열을 반환한다.

    한 번에 MAX_BACKFILL_PER_RUN 일까지만 받는다. 과거분이 많으면
    여러 번의 배치에 걸쳐 서서히 채워진다 — 첫날부터 완전한 그래프가
    나오지는 않지만 차단당하는 것보다 낫다.
    """
    currencies = currencies or ([config.BASE_CURRENCY] + config.PEER_CURRENCIES)
    years = years or config.HISTORY_YEARS

    cached = load_cache()
    today = date.today()
    start = today - timedelta(days=365 * years)

    # NBG 는 영업일 기준으로 공표한다. 주말은 애초에 시도하지 않는다.
    wanted = [d.date() for d in pd.bdate_range(start, today)]
    have = set(cached.index.date) if not cached.empty else set()

    # 필요한 통화 열이 빠진 날짜도 다시 받아야 한다.
    missing_cols = [c for c in currencies if c not in cached.columns]
    if missing_cols and not cached.empty:
        log.info("새 통화 %s 때문에 전체를 다시 받습니다.", missing_cols)
        have = set()

    todo = [d for d in wanted if d not in have]
    if not todo:
        log.info("환율 캐시가 최신입니다 (%d일).", len(cached))
        return cached

    # 최근 날짜부터 채운다. 중간에 멈춰도 최신 구간은 확보된다.
    todo.sort(reverse=True)
    limited = todo[:config.MAX_BACKFILL_PER_RUN]
    log.info("환율 %d일 필요, 이번 실행에서 %d일 수집", len(todo), len(limited))

    rows, failures = {}, 0
    for d in limited:
        try:
            day_rates = fetch_day(d, currencies)
            if day_rates:
                rows[pd.Timestamp(d)] = day_rates
        except Exception as exc:
            failures += 1
            if failures <= 3:
                log.warning("NBG %s 실패: %s", d, exc)
            if failures > 20:
                log.error("연속 실패가 많아 수집을 중단합니다.")
                break
        time.sleep(config.NBG_REQUEST_DELAY)

    if rows:
        fresh = pd.DataFrame.from_dict(rows, orient="index")
        combined = (pd.concat([cached, fresh])
                    if not cached.empty else fresh)
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        save_cache(combined)
        log.info("환율 캐시 갱신: %d일 (신규 %d, 실패 %d)",
                 len(combined), len(rows), failures)
        return combined

    if cached.empty:
        raise RuntimeError(f"NBG 환율을 하나도 받지 못했습니다 (실패 {failures}건)")

    log.warning("신규 수집 실패, 기존 캐시를 사용합니다 (%d일)", len(cached))
    return cached


def remaining_backfill(years: int | None = None) -> int:
    """아직 채우지 못한 과거 일수. 화면에 진행 상황을 알리는 데 쓴다."""
    years = years or config.HISTORY_YEARS
    cached = load_cache()
    if cached.empty:
        return len(pd.bdate_range(date.today() - timedelta(days=365 * years),
                                  date.today()))
    wanted = pd.bdate_range(date.today() - timedelta(days=365 * years), date.today())
    have = set(cached.index.date)
    return sum(1 for d in wanted if d.date() not in have)

