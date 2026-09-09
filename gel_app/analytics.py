"""분석·예측 모델 계층.

무거운 연산은 모두 여기서 수행하며, 배치에서 하루 한 번만 호출한다.
statsmodels / arch 가 없는 환경에서도 동작하도록 폴백을 둔다.
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd

from . import config

log = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

# 라리는 2.67 수준이라 원화(1355)와 같은 자리수로 반올림하면 값이 뭉개진다.
# 예: 2.4379 를 소수 1자리로 반올림하면 2.4 가 되어 그래프가 계단 모양이 된다.
DIGITS = getattr(config, "PRICE_DIGITS", 4)

try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.seasonal import STL
    HAS_STATSMODELS = True
except ImportError:                                    # pragma: no cover
    HAS_STATSMODELS = False
    log.warning("statsmodels 미설치 - ARIMA 는 폴백 로직을 사용합니다.")

try:
    from arch import arch_model
    HAS_ARCH = True
except ImportError:                                    # pragma: no cover
    HAS_ARCH = False
    log.warning("arch 미설치 - GARCH 는 EWMA 폴백을 사용합니다.")


# ---------------------------------------------------------------- 유틸
def monthly(s: pd.Series) -> pd.Series:
    return s.resample("ME").last().dropna()


def log_returns(s: pd.Series) -> pd.Series:
    return np.log(s / s.shift(1)).dropna()


def future_labels(last: pd.Timestamp, n: int) -> list[str]:
    idx = pd.date_range(last, periods=n + 1, freq="ME")[1:]
    return [d.strftime("%Y-%m") for d in idx]


# ---------------------------------------------------------------- 시나리오 밴드
def scenario_bands(px: pd.Series, months: int) -> dict:
    """강세·중립·약세 3개 경로. 과거 월간 변동성을 기준으로 폭을 정한다."""
    m = monthly(px)
    ret = log_returns(m)
    sigma = float(ret.std())
    last = float(m.iloc[-1])

    horizon = np.arange(1, months + 1)
    # 시간에 따라 sqrt(t) 로 벌어지는 표준적 확산
    spread = sigma * np.sqrt(horizon) * last

    base = last + np.cumsum(np.full(months, ret.mean() * last))
    bull = base - spread * 1.0     # 원화 강세 = 환율 하락
    bear = base + spread * 1.0     # 원화 약세 = 환율 상승

    return {
        "labels": future_labels(m.index[-1], months),
        "bull": np.round(bull, DIGITS).tolist(),
        "base": np.round(base, DIGITS).tolist(),
        "bear": np.round(bear, DIGITS).tolist(),
        "anchor": round(last, DIGITS),
        "sigma_monthly": round(sigma, 5),
    }


# ---------------------------------------------------------------- ARIMA
def arima_forecast(px: pd.Series, months: int, allow_seasonal: bool = True) -> dict:
    """라리는 관광 성수기 계절성이 뚜렷해 SARIMA 를 먼저 시도한다."""
    m = monthly(px)
    if HAS_STATSMODELS and len(m) >= 30:
        # 계절항(12개월)을 포함한 SARIMA → 실패 시 일반 ARIMA
        for order, seasonal, name in (
            ((1, 1, 1), (1, 0, 1, 12), "SARIMA(1,1,1)(1,0,1)[12]"),
            ((1, 1, 1), (0, 0, 0, 0), "ARIMA(1,1,1)"),
        ):
            if not allow_seasonal and seasonal != (0, 0, 0, 0):
                continue
            try:
                model = ARIMA(m.values, order=order,
                              seasonal_order=seasonal).fit()
                if not model.mle_retvals.get("converged", True):
                    continue
                fc = model.get_forecast(steps=months)
                ci = fc.conf_int(alpha=0.20)      # 80% 구간
                return {
                    "labels": future_labels(m.index[-1], months),
                    "mean": np.round(fc.predicted_mean, 4).tolist(),
                    "lower": np.round(ci[:, 0], 4).tolist(),
                    "upper": np.round(ci[:, 1], 4).tolist(),
                    "method": name,
                }
            except Exception as exc:               # pragma: no cover
                log.warning("%s 실패: %s", name, exc)

    # 폴백: 랜덤워크 + 변동성 구간
    last = float(m.iloc[-1])
    sigma = float(log_returns(m).std()) * last
    h = np.arange(1, months + 1)
    mean = np.full(months, last)
    band = sigma * np.sqrt(h) * 1.28
    return {
        "labels": future_labels(m.index[-1], months),
        "mean": np.round(mean, 4).tolist(),
        "lower": np.round(mean - band, 4).tolist(),
        "upper": np.round(mean + band, 4).tolist(),
        "method": "Random Walk (폴백)",
    }


# ---------------------------------------------------------------- GARCH
def garch_volatility(px: pd.Series, horizon: int = 20) -> dict:
    ret = log_returns(px) * 100
    hist = ret.rolling(20).std().dropna() * np.sqrt(252)

    if HAS_ARCH and len(ret) > 250:
        try:
            res = arch_model(ret, vol="Garch", p=1, q=1, dist="t").fit(disp="off")
            fc = res.forecast(horizon=horizon, reindex=False)
            var = fc.variance.values[-1]
            ann = np.sqrt(var) * np.sqrt(252)
            return {
                "history_labels": [d.strftime("%Y-%m-%d") for d in hist.index[-120:]],
                "history": np.round(hist.values[-120:], 2).tolist(),
                "forecast": np.round(ann, 2).tolist(),
                "method": "GARCH(1,1)-t",
            }
        except Exception as exc:                   # pragma: no cover
            log.warning("GARCH 실패, EWMA 폴백: %s", exc)

    ewma = ret.ewm(span=30).std().iloc[-1] * np.sqrt(252)
    return {
        "history_labels": [d.strftime("%Y-%m-%d") for d in hist.index[-120:]],
        "history": np.round(hist.values[-120:], 2).tolist(),
        "forecast": np.round(np.full(horizon, float(ewma)), 2).tolist(),
        "method": "EWMA (폴백)",
    }


# ---------------------------------------------------------------- 계절성
def seasonality(px: pd.Series) -> dict:
    """STL 로 추세·계절·잔차를 분해한다.

    라리는 여름 관광 성수기에 강세를 보이는 패턴이 뚜렷해서, 계절 성분을
    따로 보지 않으면 그 시기의 움직임을 추세 변화로 오해하기 쉽다.
    """
    m = monthly(px)
    if not HAS_STATSMODELS or len(m) < 30:
        return {"available": False,
                "reason": f"데이터 부족 ({len(m)}개월, 최소 30개월 필요)"}

    try:
        res = STL(m, period=12, robust=True).fit()
    except Exception as exc:                        # pragma: no cover
        log.warning("STL 분해 실패: %s", exc)
        return {"available": False, "reason": str(exc)}

    labels = [d.strftime("%Y-%m") for d in m.index]
    seasonal = pd.Series(res.seasonal.values, index=m.index)

    # 월별 평균 계절 효과 — 어느 달이 강세/약세인지 한눈에 본다.
    by_month = seasonal.groupby(seasonal.index.month).mean()
    names = ["1월", "2월", "3월", "4월", "5월", "6월",
             "7월", "8월", "9월", "10월", "11월", "12월"]

    strength = float(np.var(res.seasonal) /
                     (np.var(res.seasonal) + np.var(res.resid) + 1e-12))

    return {
        "available": True,
        "labels": labels,
        "observed": np.round(m.values, 4).tolist(),
        "trend": np.round(res.trend, 4).tolist(),
        "seasonal": np.round(res.seasonal, 4).tolist(),
        "resid": np.round(res.resid, 4).tolist(),
        "month_labels": names,
        "month_effect": [round(float(by_month.get(i, 0.0)), 4)
                         for i in range(1, 13)],
        "strength": round(strength, 3),
        "note": ("계절성 강도는 0~1 이며, 높을수록 매년 같은 시기에 "
                 "반복되는 패턴이 뚜렷하다는 뜻입니다."),
    }


# ---------------------------------------------------------------- 몬테카를로
def monte_carlo(px: pd.Series, months: int, n_sims: int) -> dict:
    m = monthly(px)
    ret = log_returns(m)
    mu, sigma = float(ret.mean()), float(ret.std())
    last = float(m.iloc[-1])

    rng = np.random.default_rng(42)
    shocks = rng.normal(mu, sigma, size=(n_sims, months))
    paths = last * np.exp(np.cumsum(shocks, axis=1))

    pcts = {p: np.percentile(paths, p, axis=0) for p in (5, 25, 50, 75, 95)}
    terminal = paths[:, -1]

    return {
        "labels": future_labels(m.index[-1], months),
        "p05": np.round(pcts[5], DIGITS).tolist(),
        "p25": np.round(pcts[25], DIGITS).tolist(),
        "p50": np.round(pcts[50], DIGITS).tolist(),
        "p75": np.round(pcts[75], DIGITS).tolist(),
        "p95": np.round(pcts[95], DIGITS).tolist(),
        "n_sims": n_sims,
        "terminal_mean": round(float(terminal.mean()), DIGITS),
        "terminal_p05": round(float(np.percentile(terminal, 5)), DIGITS),
        "terminal_p95": round(float(np.percentile(terminal, 95)), DIGITS),
    }


# ---------------------------------------------------------------- VaR / CVaR
def tail_risk(px: pd.Series, horizons=(1, 3, 6, 12)) -> dict:
    m = monthly(px)
    ret = log_returns(m)
    sigma = float(ret.std())
    last = float(m.iloc[-1])

    var95, cvar99 = [], []
    for h in horizons:
        s = sigma * np.sqrt(h)
        var95.append(round(last * (np.exp(1.645 * s) - 1), DIGITS))
        cvar99.append(round(last * (np.exp(2.665 * s) - 1), DIGITS))

    return {
        "labels": [f"{h}개월" for h in horizons],
        "var95": var95,
        "cvar99": cvar99,
        "note": "정규분포 가정 기준, 라리 약세 방향 손실폭(GEL)",
    }


# ---------------------------------------------------------------- 요인 분해
def decomposition(raw: dict[str, pd.Series], months: int = 12) -> dict:
    """월별 환율 변동분을 조지아 고유 요인의 기여도로 분해한다.

    한국판의 금리차·무역수지 대신 송금·관광·FDI 를 쓴다. 조지아는
    이 셋이 외화 공급의 대부분을 차지한다.
    """
    m_px = monthly(raw["usdgel"])
    d_px = m_px.diff().dropna()

    factors = pd.DataFrame({
        "송금요인": monthly(raw["remittance"]),
        "관광요인": monthly(raw["tourism"]),
        "투자요인": monthly(raw["fdi"]),
        "정책요인": monthly(raw["nbg_rate"]),
    }).diff()

    df = pd.concat([d_px.rename("y"), factors], axis=1).dropna()
    names = ["송금요인", "관광요인", "투자요인", "정책요인"]
    if len(df) < 12:
        return {"labels": [], "series": {}, "coefficients": {}, "importance": {}}

    X = df[names].values
    y = df["y"].values
    beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)

    contrib = (X * beta[1:])[-months:]
    tail = df.index[-months:]

    x_sd = X.std(axis=0)
    y_sd = y.std()
    std_beta = beta[1:] * x_sd / y_sd if y_sd else np.zeros(len(names))
    total = np.abs(std_beta).sum() or 1.0

    return {
        "labels": [d.strftime("%Y-%m") for d in tail],
        "series": {n: np.round(contrib[:, i], 4).tolist()
                   for i, n in enumerate(names)},
        "coefficients": {n: round(float(beta[i + 1]), 6)
                         for i, n in enumerate(names)},
        "importance": {n: round(float(abs(std_beta[i]) / total), 3)
                       for i, n in enumerate(names)},
    }


# ---------------------------------------------------------------- 상관관계
def correlations(raw: dict[str, pd.Series], window: int = 12) -> dict:
    """라리와 지역 통화·글로벌 지표의 상관관계.

    조지아는 러시아·터키·아르메니아와 교역·송금 연결이 강해 이들 통화와
    동조화가 나타난다. 한국판의 코스피 대신 지역 통화를 본다.
    """
    df = pd.DataFrame({
        "USD/GEL": monthly(raw["usdgel"]),
        "EUR/GEL": monthly(raw["eurgel"]),
        "RUB/GEL": monthly(raw["rubgel"]),
        "TRY/GEL": monthly(raw["trygel"]),
        "DXY": monthly(raw["dxy"]),
        "유가": monthly(raw["oil"]),
    }).pct_change().dropna()

    if len(df) < window:
        return {"assets": [], "matrix": []}

    corr = df.corr().round(2)
    return {"assets": corr.columns.tolist(), "matrix": corr.values.tolist()}


# ---------------------------------------------------------------- 백테스팅
def backtest(px: pd.Series, test_months: int = 12) -> dict:
    """단순 walk-forward 방식으로 모델별 RMSE 를 비교한다."""
    m = monthly(px)
    if len(m) < test_months + 24:
        test_months = max(4, len(m) - 24)

    train, test = m.iloc[:-test_months], m.iloc[-test_months:]
    actual = test.values
    results: dict[str, float] = {}

    # 1) 랜덤워크 (벤치마크)
    rw = np.full(test_months, float(train.iloc[-1]))
    results["랜덤워크"] = float(np.sqrt(np.mean((rw - actual) ** 2)))

    # 2) 이동평균
    ma = np.full(test_months, float(train.iloc[-6:].mean()))
    results["이동평균"] = float(np.sqrt(np.mean((ma - actual) ** 2)))

    # 3) ARIMA
    if HAS_STATSMODELS:
        try:
            fc = ARIMA(train.values, order=(1, 1, 1)).fit() \
                .forecast(steps=test_months)
            results["ARIMA"] = float(np.sqrt(np.mean((fc - actual) ** 2)))
        except Exception:                          # pragma: no cover
            pass

    # 4) 드리프트 반영
    drift = float(train.diff().tail(12).mean())
    dr = float(train.iloc[-1]) + drift * np.arange(1, test_months + 1)
    results["드리프트"] = float(np.sqrt(np.mean((dr - actual) ** 2)))

    # 5) 앙상블 (위 모델 평균)
    preds = [rw, ma, dr]
    ens = np.mean(preds, axis=0)
    results["앙상블"] = float(np.sqrt(np.mean((ens - actual) ** 2)))

    ordered = dict(sorted(results.items(), key=lambda kv: kv[1]))
    return {
        "labels": list(ordered.keys()),
        "rmse": [round(v, DIGITS) for v in ordered.values()],
        "test_months": test_months,
        "note": "값이 낮을수록 예측 오차가 작습니다.",
    }


# ---------------------------------------------------------------- 볼린저 밴드
def bollinger(px: pd.Series, window: int = 20, k: float = 2.0) -> dict:
    tail = px.tail(120)
    ma = tail.rolling(window).mean()
    sd = tail.rolling(window).std()
    valid = ma.dropna().index
    return {
        "labels": [d.strftime("%Y-%m-%d") for d in valid],
        "price": np.round(tail.loc[valid].values, DIGITS).tolist(),
        "ma": np.round(ma.loc[valid].values, DIGITS).tolist(),
        "upper": np.round((ma + k * sd).loc[valid].values, DIGITS).tolist(),
        "lower": np.round((ma - k * sd).loc[valid].values, DIGITS).tolist(),
    }


# ---------------------------------------------------------------- 전체 실행
def currency_crosses(raw: dict[str, pd.Series]) -> dict[str, dict]:
    """NBG의 GEL 기준 환율을 USD 기준 주요 통화 교차환율로 변환한다."""
    usd = raw["usdgel"].rename("usdgel")
    out = {}
    for key, code, pair, digits in (
        ("cnygel", "CNY", "USD/CNY", 4),
        ("eurgel", "EUR", "USD/EUR", 4),
        ("gbpgel", "GBP", "USD/GBP", 4),
        ("jpygel", "JPY", "USD/JPY", 3),
    ):
        if key not in raw:
            continue
        joined = pd.concat([usd, raw[key].rename(key)], axis=1).dropna().sort_index()
        joined = joined[np.isfinite(joined).all(axis=1) & (joined > 0).all(axis=1)]
        if joined.empty:
            continue
        # GEL/외화와 GEL/USD의 비율은 외화/USD, 즉 USD/외화 환율이다.
        values = joined["usdgel"] / joined[key]
        out[code] = {
            "pair": pair,
            "labels": [d.strftime("%Y-%m-%d") for d in values.index[-250:]],
            "values": np.round(values.values[-250:], digits).tolist(),
            "digits": digits,
        }
        # Fit each currency on its own full history, not the 250-point chart tail.
        out[code]["analysis"] = cross_analysis(values)
    return out


def cross_analysis(px: pd.Series) -> dict:
    """통화별 분석. 마지막 미완료 월은 월간 모델 학습에서 제외한다."""
    m = monthly(px)
    cutoff = px.index[-1].normalize() + pd.offsets.MonthEnd(0)
    complete = px if px.index[-1].normalize() == cutoff else px[px.index < px.index[-1].replace(day=1).normalize()]
    result = {"available": False, "observations": len(px),
              "history": {"labels": [d.strftime("%Y-%m") for d in m.index], "values": m.round(6).tolist()},
              "bollinger": bollinger(px)}
    if len(monthly(complete)) < 30:
        result["reason"] = "완료된 월 데이터가 30개월 이상 쌓이면 심화 분석이 제공됩니다."
        return result
    result.update({"available": True,
                   "model_as_of": complete.index[-1].strftime("%Y-%m-%d"),
                   "scenario": scenario_bands(complete, 12),
                   "arima": arima_forecast(complete, 12, allow_seasonal=False),
                   "garch": garch_volatility(px),
                   "seasonality": seasonality(complete),
                   "monte_carlo": monte_carlo(complete, 12, config.MC_SIMULATIONS),
                   "backtest": backtest(complete)})
    return result


def build_snapshot(raw: dict[str, pd.Series]) -> dict:
    """수집된 원자료로 모든 그래프 데이터를 계산한다."""
    sampled = raw.pop("_sampled", []) if isinstance(raw.get("_sampled"), list) else []
    backfill_left = raw.pop("_backfill_left", 0)

    px = raw["usdgel"]
    m_px = monthly(px)
    months = config.FORECAST_MONTHS

    latest = float(px.iloc[-1])
    prev = float(px.iloc[-2]) if len(px) > 1 else latest
    change_pct = round((latest / prev - 1) * 100, 2)

    def _daily(key: str, n: int, digits: int = 4) -> dict:
        s = raw[key].dropna()
        return {
            "labels": [d.strftime("%Y-%m-%d") for d in s.index[-n:]],
            "values": np.round(s.values[-n:], digits).tolist(),
        }

    def _monthly(key: str, n: int, digits: int = 1) -> dict:
        s = monthly(raw[key])
        return {
            "labels": [d.strftime("%Y-%m") for d in s.index[-n:]],
            "values": np.round(s.values[-n:], digits).tolist(),
        }

    # 지역 통화는 라리 기준 변화율로 비교해야 단위 차이가 사라진다.
    peers = {}
    for key, name in (("eurgel", "EUR/GEL"), ("rubgel", "RUB/GEL"),
                      ("trygel", "TRY/GEL"), ("amdgel", "AMD/GEL"),
                      ("azngel", "AZN/GEL")):
        s = raw[key].dropna()
        if len(s) < 30:
            continue
        base = float(s.iloc[-250]) if len(s) > 250 else float(s.iloc[0])
        rebased = (s / base - 1) * 100
        peers[name] = {
            "labels": [d.strftime("%Y-%m-%d") for d in rebased.index[-250:]],
            "values": np.round(rebased.values[-250:], 2).tolist(),
        }

    snap = {
        "summary": {
            "latest": round(latest, 4),
            "change_pct": change_pct,
            "history_months": len(m_px),
            "sampled_indicators": sampled,
            "backfill_left": int(backfill_left),
            "pair": "USD/GEL",
        },
        # --- 개인용 ---
        "history": {
            "labels": [d.strftime("%Y-%m") for d in m_px.index[-config.HISTORY_MONTHS:]],
            "values": np.round(m_px.values[-config.HISTORY_MONTHS:], 4).tolist(),
        },
        "scenario": scenario_bands(px, months),
        "bollinger": bollinger(px),
        "eurgel": _daily("eurgel", 250),
        "crosses": currency_crosses(raw),
        # --- 전문가용: 외화 유입 ---
        "remittance": _monthly("remittance", 24),
        "tourism": _monthly("tourism", 24),
        "fdi": _monthly("fdi", 24),
        "trade_bal": _monthly("trade_bal", 24),
        # --- 통화·정책 ---
        "nbg_rate": _monthly("nbg_rate", 24, 2),
        "larization": _monthly("larization", 24, 1),
        "intervention": _monthly("intervention", 24),
        "reserves": _monthly("reserves", 24),
        # --- 글로벌 ---
        "dxy": _daily("dxy", 250, 2),
        "oil": _daily("oil", 250, 2),
        "vix": _daily("vix", 250, 2),
        "peers": peers,
        # --- 모델 ---
        "seasonality": seasonality(px),
        "arima": arima_forecast(px, months),
        "garch": garch_volatility(px),
        "monte_carlo": monte_carlo(px, months, config.MC_SIMULATIONS),
        "tail_risk": tail_risk(px),
        "decomposition": decomposition(raw),
        "correlations": correlations(raw),
        "backtest": backtest(px),
    }

    try:
        from . import direction
        snap["direction"] = direction.build_direction(raw, snap["monte_carlo"])
    except Exception as exc:
        log.warning("방향 예측 실패: %s", exc)
        snap["direction"] = {"available": False, "reason": str(exc)}

    return snap

