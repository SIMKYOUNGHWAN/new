"""NBG 공식 환율 원본 수집. 샘플·보간 없이 유효한 공시값만 저장."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from . import config

URL = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/"
CODES = ("USD", "EUR", "RUB", "TRY", "AMD", "AZN", "CNY", "GBP", "JPY")
FILE = config.DATA_DIR / "nbg_live_rates.csv"


def fetch_day(day):
    for attempt in range(3):
        try:
            # The API accepts a single currency, not a comma-separated list.
            response = requests.get(URL, params={"date": str(day)}, timeout=(10, 25))
            response.raise_for_status()
            data = response.json()
            if not data:
                raise ValueError("빈 NBG 응답")
            effective = pd.Timestamp(data[0]["date"]).tz_localize(None).normalize()
            if not 0 <= (pd.Timestamp(day) - effective).days <= 7:
                raise ValueError("공시일 불일치")
            values = {}
            for item in data[0]["currencies"]:
                if item["code"] in CODES:
                    value = float(item["rate"]) / float(item["quantity"])
                    if not np.isfinite(value) or value <= 0:
                        raise ValueError("비정상 환율")
                    values[item["code"]] = value
            if not {"USD", "EUR"}.issubset(values):
                raise ValueError("USD/EUR 누락")
            return effective, values
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def fetch_rates():
    today = pd.Timestamp(datetime.now(ZoneInfo("Asia/Tbilisi")).date())
    start = today - pd.DateOffset(years=3)
    cached = pd.read_csv(FILE, index_col="date", parse_dates=True) if FILE.exists() else pd.DataFrame()
    # Refresh the most recent week to incorporate revised publications.
    wanted = pd.bdate_range(start, today)
    # NBG may return Saturday's effective date for Monday. Do not repeatedly
    # backfill those valid publication gaps on every scheduled run.
    todo = [d.date() for d in wanted if cached.empty or d >= today - pd.Timedelta(days=7)]
    rows, errors = {}, []
    def get(day):
        try:
            result = fetch_day(day)
            time.sleep(0.2)
            return result
        except Exception as exc:
            return str(day), str(exc)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i, (day, value) in enumerate(pool.map(get, todo)):
            if isinstance(value, dict):
                rows[day] = value
            else:
                errors.append(day)
            if (i + 1) % 100 == 0:
                print(f"NBG {i + 1}/{len(todo)}", flush=True)
    fresh = pd.DataFrame.from_dict(rows, orient="index")
    frame = pd.concat([cached, fresh])
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.loc[frame.index >= start]
    if len(frame) < 600 or not {"USD", "EUR"}.issubset(frame.columns):
        raise ValueError(f"NBG 실제 이력 부족: {len(frame)}개, 실패 {len(errors)}일")
    required = frame[["USD", "EUR"]]
    if not np.isfinite(required.to_numpy()).all() or not (required > 0).all().all():
        raise ValueError("NBG 필수 환율 누락")
    if (today - frame.index[-1]).days > 4:
        raise ValueError("NBG 최신 환율 갱신 실패")
    tmp = FILE.with_suffix(".tmp")
    frame.to_csv(tmp, index_label="date")
    tmp.replace(FILE)
    return frame, errors


if __name__ == "__main__":
    data, errors = fetch_rates()
    print("NBG 완료", len(data), data.index[-1], data.iloc[-1].to_dict(), "실패", len(errors))

