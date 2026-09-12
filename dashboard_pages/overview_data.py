"""통합 비교: 동일 날짜의 실제 관측만 사용하며 결측값을 보간하지 않는다."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
NAMES = {"KRW":"대한민국 원화","GEL":"조지아 라리화","CNY":"중국 위안화",
         "EUR":"유럽 유로화","GBP":"영국 파운드화","JPY":"일본 엔화","TRY":"터키 리라"}
ROUTES = {"KRW":"/","GEL":"/gel","CNY":"/cny","EUR":"/eur","GBP":"/gbp","JPY":"/jpy","TRY":"/try"}


def series(labels, values):
    if len(labels) != len(values):
        raise ValueError("날짜와 가격 개수가 다릅니다.")
    s = pd.Series(values, index=pd.to_datetime(labels), dtype=float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s[np.isfinite(s) & (s > 0)]


def load(root=ROOT):
    daily, monthly, sources, errors = {}, {}, {}, []
    for path, codes, source in (
        ("data/snapshot.json", ["KRW"], "기존 원화 일간 스냅샷"),
        ("gel_data/snapshot_live.json", ["GEL"], "NBG"),
        ("major_data/snapshot.json", ["CNY","EUR","GBP","JPY","TRY"], "ECB"),
    ):
        try:
            snap = json.loads((Path(root)/path).read_text(encoding="utf-8"))
            if snap.get("meta", {}).get("mode") != "live":
                raise ValueError("실제 데이터로 확인되지 않음")
            for code in codes:
                if code == "KRW":
                    raw = snap["bollinger"]
                    daily[code] = series(raw["labels"],raw["price"])
                    history = snap["history"]
                elif code == "GEL":
                    raw = snap["daily"]
                    daily[code] = series(raw["labels"],raw["values"])
                    history = snap["history"]
                else:
                    raw = snap["crosses"][code]
                    daily[code] = series(raw["labels"],raw["values"])
                    history = raw["analysis"]["history"]
                monthly[code] = series(history["labels"],history["values"]).resample("ME").last().dropna()
                sources[code] = source
        except (OSError, ValueError, KeyError, TypeError) as exc:
            for code in codes:
                daily.pop(code,None)
                monthly.pop(code,None)
                sources.pop(code,None)
            errors.append(f"{', '.join(codes)}: {exc}")
    return daily, monthly, sources, errors


def align(data, codes):
    return pd.concat({c:data[c] for c in codes}, axis=1,sort=True).dropna().sort_index()


def strength(prices, base):
    # Currency value in USD or KRW; rising always means stronger currency.
    return 1/prices if base == "USD" else prices.rdiv(prices["KRW"], axis=0)


def window(frame, days):
    cutoff = frame.index[-1] - pd.Timedelta(days=days)
    earlier = frame.index[frame.index <= cutoff]
    if not len(earlier):
        return None
    return frame.loc[earlier[-1]:]


def changes(values):
    result = {}
    for label, days in (("1주",7),("1개월",30),("3개월",90)):
        w = window(values, days)
        result[label] = ((w.iloc[-1]/w.iloc[0]-1)*100) if w is not None else pd.Series(np.nan,index=values.columns)
    return pd.DataFrame(result)


def forecast(monthly_prices, asof, base):
    # Use only completed calendar months shared by the selected currencies.
    m = monthly_prices[monthly_prices.index < pd.Timestamp(asof).replace(day=1).normalize()].tail(37)
    if len(m) < 25:
        return {}
    values = strength(m,base)
    returns = np.log(values/values.shift()).dropna()
    h = np.arange(1,13)
    output = {}
    for code in values:
        mu, sd = float(returns[code].mean()),float(returns[code].std())
        output[code] = {"labels":[(pd.Timestamp(asof)+pd.DateOffset(months=int(i))).strftime("%Y-%m-%d") for i in h],
                        "median":(100*np.exp(mu*h)).tolist(),
                        "lower":(100*np.exp(mu*h-1.644854*sd*np.sqrt(h))).tolist(),
                        "upper":(100*np.exp(mu*h+1.644854*sd*np.sqrt(h))).tolist(),
                        "train_start":str(m.index[0].date()),"train_end":str(m.index[-1].date()),"months":len(returns)}
    return output


def convert(prices,budget):
    return prices.div(prices["KRW"],axis=0)*budget

