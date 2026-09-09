"""실제 NBG 환율·공식 거시통계·현지 뉴스 배치."""
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import analytics, config, live_sources, live_context, live_news, live_analysis, live_tracking

FILE = config.DATA_DIR / "snapshot_live.json"


def load_snapshot():
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        return data if data.get("meta", {}).get("mode") == "live" else None
    except (OSError, ValueError):
        return None


def build_snapshot(rates, context, news):
    px = rates["USD"]
    result = analytics.cross_analysis(px)
    if not result.get("available"):
        raise ValueError(result.get("reason", "실제 이력 부족"))
    def daily(s):
        s = s.dropna().tail(250)
        return {"labels": s.index.strftime("%Y-%m-%d").tolist(), "values": s.round(6).tolist()}
    result["daily"] = daily(px)
    result["eurgel"] = daily(rates["EUR"])
    result["peers"] = {f"{code}/GEL": daily((rates[code].dropna().tail(250) / rates[code].dropna().tail(250).iloc[0] - 1)*100)
                       for code in ("EUR", "RUB", "TRY", "AMD", "AZN") if code in rates and rates[code].notna().sum() >= 30}
    series = {f"{code}/GEL": rates[code].dropna() for code in ("USD", "EUR", "RUB", "TRY") if code in rates}
    for key in ("dxy", "vix", "oil"):
        item = context.get(key, {})
        if item.get("available"):
            series[item["name"]] = pd.Series(item["values"], index=pd.to_datetime(item["labels"]))
    returns = pd.DataFrame({k: np.log(v/v.shift()).dropna() for k,v in series.items()}).tail(250)
    corr = returns.corr(min_periods=60)
    valid = corr.columns[corr.notna().all()]
    corr = corr.loc[valid, valid]
    result["correlations"] = {"assets": list(corr.columns), "matrix": corr.round(3).values.tolist()}
    # Exact identity, not a causal regression on unavailable monthly macro series.
    m = pd.DataFrame({"USD": rates["USD"], "EUR": rates["EUR"]}).resample("ME").last()
    eur_usd = m["EUR"] / m["USD"]
    a = np.log(m["EUR"]/m["EUR"].shift())*100
    b = -np.log(eur_usd/eur_usd.shift())*100
    factors = pd.DataFrame({"EUR/GEL 변동": a, "EUR/USD 역방향 변동": b}).dropna().tail(12)
    result["decomposition"] = {"labels": factors.index.strftime("%Y-%m").tolist(),
                               "series": {c: factors[c].round(4).tolist() for c in factors}}
    result.update({"summary": {"latest": round(float(px.iloc[-1]),4),
                               "change_pct": round(float((px.iloc[-1]/px.iloc[-2]-1)*100),3),
                               "as_of": px.index[-1].strftime("%Y-%m-%d")},
                   "context": context, "news": news, "direction": live_analysis.direction(px),
                   "forecast20": live_analysis.forecast20(px), "risk": live_analysis.risk(px),
                   "backtest": live_analysis.walk_forward(px)})
    return result


def run_batch(force=False):
    start = time.monotonic()
    rates, failures = live_sources.fetch_rates()
    context, news = live_context.collect(), live_news.collect()
    old = load_snapshot()
    # Retain only previously verified real context on temporary provider failure.
    if old:
        for key, item in list(context.items()):
            previous = old.get("context", {}).get(key, {})
            if not item.get("available") and previous.get("available"):
                context[key] = {**previous, "refresh_failed": True}
    snap = build_snapshot(rates, context, news)
    snap["meta"] = {"mode": "live", "source": "National Bank of Georgia",
                    "generated_at_display": datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d %H:%M 트빌리시"),
                    "elapsed_sec": round(time.monotonic()-start,1), "failed_dates": failures}
    # Serialize before changing prediction history.
    json.dumps(snap, allow_nan=False)
    snap["tracking"] = live_tracking.update(snap, rates["USD"])
    content = json.dumps(snap, ensure_ascii=False, allow_nan=False, indent=1)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(FILE)
    print("NBG LIVE:", snap["summary"], "news:", len(news["items"]))
    return snap


if __name__ == "__main__":
    run_batch()

