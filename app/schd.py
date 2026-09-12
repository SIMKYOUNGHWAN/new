"""SCHD actual daily data. Yahoo split-adjusted dividends must not be split again."""
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

FILE = Path(__file__).resolve().parent.parent / "schd_data" / "snapshot.json"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/SCHD"
ECB = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"


def parse_chart(payload, now=None):
    now = pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert("America/New_York")
    result = payload["chart"]["result"][0]
    if result["meta"]["symbol"] != "SCHD":
        raise ValueError("Unexpected ticker")
    dates = pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
    frame = pd.DataFrame({"close": result["indicators"]["quote"][0]["close"],
                          "adjusted": result["indicators"]["adjclose"][0]["adjclose"]}, index=dates).dropna()
    # Only completed sessions; allow an extra hour after the usual closing time.
    cutoff = now.tz_localize(None).normalize()
    frame = frame.loc[frame.index <= cutoff if now.hour >= 17 else frame.index < cutoff]
    if frame.index.has_duplicates or len(frame) < 1500 or not np.isfinite(frame.values).all() or not (frame > 0).all().all():
        raise ValueError("Invalid or insufficient price history")
    if (cutoff - frame.index[-1]).days > 7:
        raise ValueError("Price history is stale")
    events = result.get("events", {}).get("dividends", {})
    dividends = pd.Series({pd.Timestamp(v["date"], unit="s", tz="UTC").tz_convert("America/New_York").tz_localize(None).normalize(): float(v["amount"]) for v in events.values()}, dtype=float).sort_index()
    dividends = dividends.loc[dividends.index <= frame.index[-1]]
    if len(dividends) < 24 or not np.isfinite(dividends.values).all() or not (dividends > 0).all():
        raise ValueError("Invalid dividend history")
    return frame, dividends


def dividend_stats(dividends, asof, close, history_start):
    asof = pd.Timestamp(asof)
    ttm = dividends.loc[(dividends.index > asof - pd.DateOffset(years=1)) & (dividends.index <= asof)]
    if len(ttm) < 4:
        raise ValueError("Incomplete trailing distribution year")
    annual = []
    for year, values in dividends.groupby(dividends.index.year):
        # Exclude initial partial year and current year from growth comparisons.
        complete = year < asof.year and pd.Timestamp(history_start) <= pd.Timestamp(year, 1, 1) and len(values) >= 4
        annual.append({"year": int(year), "amount": float(values.sum()), "complete": bool(complete), "count": len(values)})
    full = {r["year"]: r["amount"] for r in annual if r["complete"]}
    end = max(full) if full else None
    growth = {}
    for years in (1, 3, 5):
        growth[str(years)] = ((full[end] / full[end-years]) ** (1/years)-1)*100 if end and end-years in full else None
    return {"ttm": float(ttm.sum()), "yield_pct": float(ttm.sum()/close*100),
            "annual": annual, "growth": growth, "growth_end": end}


def performance(frame, years):
    target = frame.index[-1] - pd.DateOffset(years=years)
    prior = frame.index[frame.index <= target]
    if not len(prior):
        return None
    view = frame.loc[prior[-1]:].copy()
    wealth = pd.DataFrame({"USD": view.adjusted, "KRW": view.adjusted * view.fx})
    wealth = wealth / wealth.iloc[0] * 100
    days = (wealth.index[-1]-wealth.index[0]).days
    return {"view": view, "wealth": wealth, "return": (wealth.iloc[-1]/100-1)*100,
            "cagr": ((wealth.iloc[-1]/100)**(365.25/days)-1)*100,
            "mdd": (wealth/wealth.cummax()-1).min()*100}


def income(budget, price, fx, ttm, withholding):
    if budget < 0 or min(price, fx) <= 0 or ttm < 0 or not 0 <= withholding <= 100:
        raise ValueError("Invalid income assumptions")
    shares = int(np.floor(budget/fx/price))
    cash = budget/fx-shares*price
    gross = shares*ttm
    return {"shares": shares, "cash_usd": cash, "gross": gross, "net": gross*(1-withholding/100)}


def scenario(budget, price, fx, ttm, withholding, price_change, fx_change):
    if price_change <= -100 or fx_change <= -100:
        raise ValueError("Invalid scenario")
    result = income(budget, price, fx, ttm, withholding)
    ending = (result["shares"]*price*(1+price_change/100)+result["cash_usd"]+result["net"])*fx*(1+fx_change/100)
    return ending


def load_snapshot():
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        if data["meta"]["mode"] != "actual":
            return None
        return data
    except (OSError, ValueError, KeyError):
        return None


def run_batch():
    with requests.Session() as session:
        session.headers["User-Agent"] = "Mozilla/5.0"
        session.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504])))
        response = session.get(YAHOO, params={"range":"10y", "interval":"1d", "events":"div,splits"}, timeout=40)
        response.raise_for_status()
        prices, dividends = parse_chart(response.json())
        response = session.get(ECB, timeout=60)
        response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        rates = pd.read_csv(io.BytesIO(archive.read("eurofxref-hist.csv")), parse_dates=["Date"]).set_index("Date").sort_index()
    rates = rates[["USD", "KRW"]].apply(pd.to_numeric, errors="coerce").dropna()
    rates = rates.loc[(rates > 0).all(axis=1)]
    frame = prices.join((rates.KRW/rates.USD).rename("fx"), how="inner").sort_index()
    if len(frame) < 1500 or (prices.index[-1]-frame.index[-1]).days > 7:
        raise ValueError("Insufficient or stale common exchange-rate history")
    stats = dividend_stats(dividends, prices.index[-1], float(prices.close.iloc[-1]), prices.index[0])
    snapshot = {"meta": {"mode":"actual", "generated_at": datetime.now(timezone.utc).isoformat(),
                              "price_asof": str(prices.index[-1].date()), "common_asof": str(frame.index[-1].date()),
                              "price_source":YAHOO, "fx_source":ECB},
                "latest_price":float(prices.close.iloc[-1]), "dividend":stats,
                "history": {"dates":frame.index.strftime("%Y-%m-%d").tolist(),
                            **{c:frame[c].round(8).tolist() for c in frame.columns}},
                "distributions":[{"ex_date":str(d.date()), "amount":float(v)} for d,v in dividends.items()]}
    content = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    FILE.parent.mkdir(exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(FILE)
    print("SCHD snapshot:", snapshot["meta"]["price_asof"], "TTM", stats["ttm"])


if __name__ == "__main__":
    run_batch()
