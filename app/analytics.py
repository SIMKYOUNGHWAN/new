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

try:
    from statsmodels.tsa.arima.model import ARIMA
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
        "bull": np.round(bull, 1).tolist(),
        "base": np.round(base, 1).tolist(),
        "bear": np.round(bear, 1).tolist(),
        "anchor": round(last, 1),
        "sigma_monthly": round(sigma, 5),
    }


# ---------------------------------------------------------------- ARIMA
def arima_forecast(px: pd.Series, months: int) -> dict:
    m = monthly(px)
    if HAS_STATSMODELS and len(m) >= 24:
        try:
            model = ARIMA(m.values, order=(1, 1, 1)).fit()
            fc = model.get_forecast(steps=months)
            mean = fc.predicted_mean
            ci = fc.conf_int(alpha=0.20)          # 80% 구간
            return {
                "labels": future_labels(m.index[-1], months),
                "mean": np.round(mean, 1).tolist(),
                "lower": np.round(ci[:, 0], 1).tolist(),
                "upper": np.round(ci[:, 1], 1).tolist(),
                "method": "ARIMA(1,1,1)",
            }
        except Exception as exc:                   # pragma: no cover
            log.warning("ARIMA 실패, 폴백 사용: %s", exc)

    # 폴백: 랜덤워크 + 변동성 구간
    last = float(m.iloc[-1])
    sigma = float(log_returns(m).std()) * last
    h = np.arange(1, months + 1)
    mean = np.full(months, last)
    band = sigma * np.sqrt(h) * 1.28
    return {
        "labels": future_labels(m.index[-1], months),
        "mean": np.round(mean, 1).tolist(),
        "lower": np.round(mean - band, 1).tolist(),
        "upper": np.round(mean + band, 1).tolist(),
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
        "p05": np.round(pcts[5], 1).tolist(),
        "p25": np.round(pcts[25], 1).tolist(),
        "p50": np.round(pcts[50], 1).tolist(),
        "p75": np.round(pcts[75], 1).tolist(),
        "p95": np.round(pcts[95], 1).tolist(),
        "n_sims": n_sims,
        "terminal_mean": round(float(terminal.mean()), 1),
        "terminal_p05": round(float(np.percentile(terminal, 5)), 1),
        "terminal_p95": round(float(np.percentile(terminal, 95)), 1),
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
        var95.append(round(last * (np.exp(1.645 * s) - 1), 1))
        cvar99.append(round(last * (np.exp(2.665 * s) - 1), 1))

    return {
        "labels": [f"{h}개월" for h in horizons],
        "var95": var95,
        "cvar99": cvar99,
        "note": "정규분포 가정 기준, 원화 약세 방향 손실폭(원)",
    }


# ---------------------------------------------------------------- 요인 분해
def decomposition(raw: dict[str, pd.Series], months: int = 12) -> dict:
    """월별 환율 변동분을 회귀계수 기여도로 분해한다."""
    m_px = monthly(raw["usdkrw"])
    d_px = m_px.diff().dropna()

    factors = pd.DataFrame({
        "금리요인": monthly(raw["kr_rate"]) - monthly(raw["us_rate"]),
        "무역요인": monthly(raw["trade_bal"]),
        "심리요인": monthly(raw["cds"]),
    }).diff()

    df = pd.concat([d_px.rename("y"), factors], axis=1).dropna()
    if len(df) < 12:
        return {"labels": [], "series": {}}

    X = df[["금리요인", "무역요인", "심리요인"]].values
    y = df["y"].values
    X_ = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X_, y, rcond=None)

    contrib = X * beta[1:]
    tail = df.index[-months:]
    contrib = contrib[-months:]

    # 요인마다 단위가 달라 원계수는 비교 불가하므로 표준화 계수를 함께 낸다.
    names = ["금리요인", "무역요인", "심리요인"]
    x_sd = X.std(axis=0)
    y_sd = y.std()
    std_beta = beta[1:] * x_sd / y_sd if y_sd else np.zeros(3)
    total = np.abs(std_beta).sum() or 1.0

    return {
        "labels": [d.strftime("%Y-%m") for d in tail],
        "series": {n: np.round(contrib[:, i], 2).tolist()
                   for i, n in enumerate(names)},
        "coefficients": {n: round(float(beta[i + 1]), 3)
                         for i, n in enumerate(names)},
        "importance": {n: round(float(abs(std_beta[i]) / total), 3)
                       for i, n in enumerate(names)},
    }


# ---------------------------------------------------------------- 상관관계
def correlations(raw: dict[str, pd.Series], window: int = 12) -> dict:
    df = pd.DataFrame({
        "USD/KRW": monthly(raw["usdkrw"]),
        "DXY": monthly(raw["dxy"]),
        "KOSPI": monthly(raw["kospi"]),
        "유가": monthly(raw["oil"]),
        "CDS": monthly(raw["cds"]),
    }).pct_change().dropna()

    if len(df) < window:
        return {"assets": [], "matrix": []}

    corr = df.corr().round(2)
    return {
        "assets": corr.columns.tolist(),
        "matrix": corr.values.tolist(),
    }


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
        "rmse": [round(v, 2) for v in ordered.values()],
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
        "price": np.round(tail.loc[valid].values, 1).tolist(),
        "ma": np.round(ma.loc[valid].values, 1).tolist(),
        "upper": np.round((ma + k * sd).loc[valid].values, 1).tolist(),
        "lower": np.round((ma - k * sd).loc[valid].values, 1).tolist(),
    }


# ---------------------------------------------------------------- 전체 실행
def build_snapshot(raw: dict[str, pd.Series]) -> dict:
    """수집된 원자료로 모든 그래프 데이터를 계산한다."""
    px = raw["usdkrw"]
    m_px = monthly(px)
    months = config.FORECAST_MONTHS

    latest = float(px.iloc[-1])
    prev = float(px.iloc[-2]) if len(px) > 1 else latest
    change_pct = round((latest / prev - 1) * 100, 2)

    kr, us = monthly(raw["kr_rate"]), monthly(raw["us_rate"])
    gap = (kr - us).dropna().tail(24)

    return {
        "summary": {
            "latest": round(latest, 2),
            "change_pct": change_pct,
            "history_months": len(m_px),
        },
        # --- 개인용 ---
        "history": {
            "labels": [d.strftime("%Y-%m") for d in m_px.index[-config.HISTORY_MONTHS:]],
            "values": np.round(m_px.values[-config.HISTORY_MONTHS:], 1).tolist(),
        },
        "scenario": scenario_bands(px, months),
        "bollinger": bollinger(px),
        # --- 전문가용: 거시 ---
        "rate_gap": {
            "labels": [d.strftime("%Y-%m") for d in gap.index],
            "values": np.round(gap.values, 2).tolist(),
        },
        "dxy": {
            "labels": [d.strftime("%Y-%m") for d in monthly(raw["dxy"]).index[-24:]],
            "values": np.round(monthly(raw["dxy"]).values[-24:], 2).tolist(),
        },
        "trade": {
            "labels": [d.strftime("%Y-%m") for d in monthly(raw["trade_bal"]).index[-12:]],
            "values": np.round(monthly(raw["trade_bal"]).values[-12:], 1).tolist(),
        },
        "flows": {
            "labels": [d.strftime("%Y-%m") for d in monthly(raw["flows"]).index[-12:]],
            "values": np.round(monthly(raw["flows"]).values[-12:], 0).tolist(),
        },
        # --- 전문가용: 모델 ---
        "implied_vol": {
            "labels": [d.strftime("%Y-%m-%d") for d in raw["implied_vol"].index[-60:]],
            "values": np.round(raw["implied_vol"].values[-60:], 2).tolist(),
        },
        "sentiment": {
            "labels": [d.strftime("%Y-%m-%d") for d in raw["sentiment"].index[-30:]],
            "values": np.round(raw["sentiment"].values[-30:], 2).tolist(),
        },
        "cds": {
            "labels": [d.strftime("%Y-%m") for d in monthly(raw["cds"]).index[-18:]],
            "values": np.round(monthly(raw["cds"]).values[-18:], 1).tolist(),
        },
        "carry": {
            "labels": [d.strftime("%Y-%m") for d in monthly(raw["carry"]).index[-18:]],
            "values": np.round(monthly(raw["carry"]).values[-18:], 2).tolist(),
        },
        "arima": arima_forecast(px, months),
        "garch": garch_volatility(px),
        "monte_carlo": monte_carlo(px, months, config.MC_SIMULATIONS),
        "tail_risk": tail_risk(px),
        "decomposition": decomposition(raw),
        "correlations": correlations(raw),
        "backtest": backtest(px),
    }
