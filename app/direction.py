"""1개월 방향 예측.

기술적 지표를 만들고 로지스틱 회귀와 LightGBM 으로 상승/하락을 분류한다.
검증은 반드시 walk-forward 로만 한다 — 전체 데이터로 학습해 같은 데이터로
적중률을 재면 항상 높게 나오기 때문이다.

핵심 원칙: 단순 적중률만 보여주지 않는다. 다수 클래스만 찍는 기준선과
균형 정확도를 함께 내야 착시가 없다.
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:                                     # pragma: no cover
    HAS_SKLEARN = False
    log.warning("scikit-learn 미설치 - 방향 예측을 건너뜁니다.")

try:
    import lightgbm as lgb
    HAS_LGBM = True
except ImportError:                                     # pragma: no cover
    HAS_LGBM = False
    log.warning("lightgbm 미설치 - 로지스틱 회귀만 사용합니다.")


HORIZON_DAYS = 21          # 영업일 기준 약 1개월
FEATURE_NAMES_KO = {
    "rsi14": "RSI(14)",
    "ma24_ratio": "MA24 대비 비율",
    "ret_4w": "4주 수익률",
    "vol_12w": "12주 변동성",
    "dxy_ret_4w": "DXY 4주 변화",
    "rate_gap": "한미 금리차",
    "iv_level": "내재변동성",
    "iv_ret_4w": "내재변동성 4주 변화",
    "mom_ratio": "단기/장기 모멘텀",
    "dist_52w_high": "52주 고점 대비",
}


# ---------------------------------------------------------------- 특징 생성
def _rsi(s: pd.Series, window: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def build_features(raw: dict[str, pd.Series]) -> pd.DataFrame:
    """일별 환율에 거시 지표를 맞춰 붙여 특징 행렬을 만든다."""
    px = raw["usdkrw"].astype(float)

    feats = pd.DataFrame(index=px.index)
    feats["rsi14"] = _rsi(px, 14)
    feats["ma24_ratio"] = px / px.rolling(24).mean() - 1
    feats["ret_4w"] = px.pct_change(20)
    feats["vol_12w"] = np.log(px / px.shift(1)).rolling(60).std() * np.sqrt(252)
    feats["mom_ratio"] = px.rolling(20).mean() / px.rolling(120).mean() - 1
    feats["dist_52w_high"] = px / px.rolling(252).max() - 1

    # 거시 지표는 주기가 짧거나 시작일이 늦어 그대로 붙이면 앞부분이 전부
    # NaN 이 된다. 행을 버리면 학습 표본이 급감하므로, 채워 넣은 뒤
    # 그래도 결측이 많은 열은 열 단위로 제거한다.
    def _align(s: pd.Series) -> pd.Series:
        return s.astype(float).reindex(px.index).ffill().bfill()

    dxy = _align(raw["dxy"])
    feats["dxy_ret_4w"] = dxy.pct_change(20)

    feats["rate_gap"] = _align(raw["kr_rate"]) - _align(raw["us_rate"])

    iv = _align(raw["implied_vol"])
    feats["iv_level"] = iv
    feats["iv_ret_4w"] = iv.pct_change(20)

    feats = feats.replace([np.inf, -np.inf], np.nan)

    # 유효값이 60% 미만인 열은 학습에 방해만 된다.
    keep = [c for c in feats.columns if feats[c].notna().mean() >= 0.60]
    dropped = set(feats.columns) - set(keep)
    if dropped:
        log.info("결측이 많아 제외한 특징: %s", ", ".join(sorted(dropped)))

    return feats[keep]


def _target(px: pd.Series, horizon: int = HORIZON_DAYS) -> pd.Series:
    """horizon 영업일 뒤 환율이 오르면 1, 아니면 0."""
    return (px.shift(-horizon) > px).astype(float)


# ---------------------------------------------------------------- 모델
def _fit_logistic(X_tr, y_tr, X_te):
    scaler = StandardScaler().fit(X_tr)
    model = LogisticRegression(max_iter=1000, C=0.5, class_weight="balanced")
    model.fit(scaler.transform(X_tr), y_tr)
    proba = model.predict_proba(scaler.transform(X_te))[:, 1]
    return proba, model.coef_[0]


def _fit_lgbm(X_tr, y_tr, X_te):
    model = lgb.LGBMClassifier(
        n_estimators=120, learning_rate=0.05, num_leaves=7,
        max_depth=3, min_child_samples=30,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
        reg_alpha=0.5, reg_lambda=1.0,
        class_weight="balanced", verbose=-1, random_state=42,
    )
    model.fit(X_tr, y_tr)
    proba = model.predict_proba(X_te)[:, 1]
    return proba, model.feature_importances_.astype(float)


# ---------------------------------------------------------------- 검증
def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """적중률과 함께 기준선·균형정확도·혼동행렬을 낸다."""
    n = len(y_true)
    if n == 0:
        return {}

    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())

    accuracy = (tp + tn) / n
    # 다수 클래스만 계속 찍었을 때의 적중률 = 기준선
    up_rate = float(y_true.mean())
    baseline = max(up_rate, 1 - up_rate)

    tpr = tp / (tp + fn) if (tp + fn) else 0.0   # 상승 재현율
    tnr = tn / (tn + fp) if (tn + fp) else 0.0   # 하락 재현율
    balanced = (tpr + tnr) / 2

    return {
        "accuracy": round(accuracy * 100, 1),
        "baseline": round(baseline * 100, 1),
        "balanced_accuracy": round(balanced * 100, 1),
        "edge": round((accuracy - baseline) * 100, 1),
        "n_samples": n,
        "actual_up_rate": round(up_rate * 100, 1),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "recall_up": round(tpr * 100, 1),
        "recall_down": round(tnr * 100, 1),
    }


def walk_forward(X: pd.DataFrame, y: pd.Series, model_fn,
                 min_train: int = 250, step: int = 21) -> tuple:
    """과거로 학습 → 미래 예측 → 이동. 미래 정보가 새지 않는다."""
    probas, actuals, dates = [], [], []

    i = min_train
    while i < len(X):
        end = min(i + step, len(X))
        X_tr, y_tr = X.iloc[:i], y.iloc[:i]

        # 학습 구간에 두 클래스가 다 있어야 분류가 가능하다.
        if y_tr.nunique() < 2:
            i = end
            continue

        try:
            p, _ = model_fn(X_tr.values, y_tr.values, X.iloc[i:end].values)
        except Exception as exc:                        # pragma: no cover
            log.warning("walk-forward 구간 실패: %s", exc)
            i = end
            continue

        probas.extend(p)
        actuals.extend(y.iloc[i:end].values)
        dates.extend(X.index[i:end])
        i = end

    return np.array(probas), np.array(actuals), dates


# ---------------------------------------------------------------- 전체 실행
def build_direction(raw: dict[str, pd.Series], mc: dict | None = None) -> dict:
    """방향 예측 결과 전체. 실패해도 배치를 막지 않도록 dict 를 반환한다."""
    if not HAS_SKLEARN:
        return {"available": False, "reason": "scikit-learn 미설치"}

    px = raw["usdkrw"].astype(float)
    feats = build_features(raw)
    y_all = _target(px)

    # 학습에는 정답이 있는 구간만, 예측에는 마지막 행을 쓴다.
    df = pd.concat([feats, y_all.rename("y")], axis=1).dropna()
    if len(df) < 320:
        return {"available": False,
                "reason": f"데이터 부족 ({len(df)}개, 최소 320개 필요)"}

    X, y = df.drop(columns="y"), df["y"]
    cols = list(X.columns)

    models = [("로지스틱 회귀", _fit_logistic)]
    if HAS_LGBM:
        models.append(("LightGBM", _fit_lgbm))

    results, history = {}, {}
    for name, fn in models:
        p, a, d = walk_forward(X, y, fn)
        if len(p) == 0:
            continue
        m = _metrics(a, (p >= 0.5).astype(float))
        m["method"] = name
        results[name] = m
        history[name] = {
            "labels": [x.strftime("%Y-%m-%d") for x in d],
            "proba": np.round(p * 100, 1).tolist(),
        }

    if not results:
        return {"available": False, "reason": "검증 구간을 만들지 못했습니다"}

    # 균형 정확도가 가장 높은 모델을 대표로 삼는다(단순 적중률은 편향된다).
    best_name = max(results, key=lambda k: results[k]["balanced_accuracy"])
    best_fn = dict(models)[best_name]

    # 현재 시점 예측: 마지막 관측 행에는 정답이 없으므로 따로 뽑는다.
    live_row = feats.dropna().iloc[[-1]]
    live_date = live_row.index[0]
    try:
        proba_now, importance = best_fn(X.values, y.values, live_row[cols].values)
        up_prob = float(proba_now[0])
    except Exception as exc:                            # pragma: no cover
        log.warning("현재 시점 예측 실패: %s", exc)
        return {"available": False, "reason": str(exc)}

    imp = np.abs(np.asarray(importance, dtype=float))
    total = imp.sum() or 1.0
    ranked = sorted(zip(cols, imp / total), key=lambda kv: kv[1], reverse=True)[:6]

    out = {
        "available": True,
        "as_of": live_date.strftime("%Y-%m-%d"),
        "horizon_days": HORIZON_DAYS,
        "best_model": best_name,
        "up_probability": round(up_prob * 100, 1),
        "down_probability": round((1 - up_prob) * 100, 1),
        "metrics": results,
        "history": history,
        "importance": {
            "labels": [FEATURE_NAMES_KO.get(k, k) for k, _ in ranked],
            "values": [round(v * 100, 1) for _, v in ranked],
        },
        "caveat": (
            "방향 예측은 동전 던지기보다 약간 나은 수준입니다. "
            "적중률은 반드시 기준선과 비교해 읽으세요."
        ),
    }

    # 1개월 수치 전망은 몬테카를로 결과를 첫 달에서 잘라 쓴다.
    if mc:
        out["level_1m"] = {
            "median": mc["p50"][0],
            "lower": mc["p05"][0],
            "upper": mc["p95"][0],
        }

    return out
