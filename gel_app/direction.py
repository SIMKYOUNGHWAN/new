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
    "vix_level": "VIX 수준",
    "oil_ret_4w": "유가 4주 변화",
    "eur_ret_4w": "EUR/GEL 4주 변화",
    "rub_ret_4w": "RUB/GEL 4주 변화",
    "try_ret_4w": "TRY/GEL 4주 변화",
    "mom_ratio": "단기/장기 모멘텀",
    "dist_52w_high": "52주 고점 대비",
    "month_sin": "계절성(상·하반기)",
    "month_cos": "계절성(연초·연말)",
    "flat_streak": "무변동 지속일",
}


# ---------------------------------------------------------------- 특징 생성
def _rsi(s: pd.Series, window: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def build_features(raw: dict[str, pd.Series]) -> pd.DataFrame:
    """일별 환율에 지역 통화·글로벌 지표를 맞춰 붙여 특징 행렬을 만든다.

    한국판의 한미 금리차·내재변동성 대신 지역 통화(RUB·TRY·EUR)와
    계절성 항을 쓴다. 조지아는 관광 성수기 패턴이 뚜렷하다.
    """
    px = raw["usdgel"].astype(float)

    feats = pd.DataFrame(index=px.index)
    feats["rsi14"] = _rsi(px, 14)
    feats["ma24_ratio"] = px / px.rolling(24).mean() - 1
    feats["ret_4w"] = px.pct_change(20)
    feats["vol_12w"] = np.log(px / px.shift(1)).rolling(60).std() * np.sqrt(252)
    feats["mom_ratio"] = px.rolling(20).mean() / px.rolling(120).mean() - 1
    feats["dist_52w_high"] = px / px.rolling(252).max() - 1

    # NBG 개입으로 며칠씩 같은 값이 이어지는 구간이 많다. 그 자체가 신호다.
    unchanged = (px.diff().abs() < 1e-9).astype(int)
    feats["flat_streak"] = (unchanged.groupby((unchanged == 0).cumsum())
                            .cumsum().clip(0, 15))

    # 관광 성수기 계절성을 연속값으로 인코딩한다.
    doy = px.index.dayofyear.to_numpy(dtype=float)
    feats["month_sin"] = np.sin(2 * np.pi * doy / 365.25)
    feats["month_cos"] = np.cos(2 * np.pi * doy / 365.25)

    def _align(s: pd.Series) -> pd.Series:
        return s.astype(float).reindex(px.index).ffill().bfill()

    feats["dxy_ret_4w"] = _align(raw["dxy"]).pct_change(20)
    feats["oil_ret_4w"] = _align(raw["oil"]).pct_change(20)
    feats["vix_level"] = _align(raw["vix"])

    for key, col in (("eurgel", "eur_ret_4w"), ("rubgel", "rub_ret_4w"),
                     ("trygel", "try_ret_4w")):
        if key in raw:
            feats[col] = _align(raw[key]).pct_change(20)

    feats = feats.replace([np.inf, -np.inf], np.nan)

    keep = [c for c in feats.columns if feats[c].notna().mean() >= 0.60]
    dropped = set(feats.columns) - set(keep)
    if dropped:
        log.info("결측이 많아 제외한 특징: %s", ", ".join(sorted(dropped)))

    return feats[keep]


def _target(px: pd.Series, horizon: int = HORIZON_DAYS) -> pd.Series:
    """horizon 영업일 뒤 환율이 오르면 1, 아니면 0."""
    return (px.shift(-horizon) > px).astype(float)


def _flat_share(px: pd.Series, horizon: int = HORIZON_DAYS,
                threshold: float = 0.001) -> float:
    """변화율이 threshold 미만인 구간의 비율.

    NBG 가 개입하면 라리가 며칠씩 사실상 고정된다. 이런 구간은 상승도
    하락도 아닌데 이진 분류에서는 강제로 한쪽에 배정되어 지표를 왜곡한다.
    얼마나 섞여 있는지 알아야 적중률을 제대로 읽을 수 있다.
    """
    chg = (px.shift(-horizon) / px - 1).abs().dropna()
    if len(chg) == 0:
        return 0.0
    return float((chg < threshold).mean())


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


# ---------------------------------------------------------------- 확률 보정
class PlattCalibrator:
    """Platt scaling. 원 확률의 로짓에 1차원 로지스틱을 다시 적합한다.

    트리 모델은 확률을 0 또는 1 쪽으로 과하게 밀어내는 경향이 있다.
    walk-forward 로 얻은 out-of-fold 확률로 보정하므로 정보 누수가 없다.
    표본이 수백 건 수준이라 isotonic 대신 Platt 을 쓴다 — isotonic 은
    이 크기에서 과적합한다.
    """

    def __init__(self):
        self.model = None

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p)).reshape(-1, 1)

    def fit(self, proba: np.ndarray, actual: np.ndarray) -> "PlattCalibrator":
        if len(np.unique(actual)) < 2 or len(proba) < 40:
            return self          # 보정을 신뢰할 수 없으면 그대로 둔다
        try:
            m = LogisticRegression(max_iter=1000)
            m.fit(self._logit(proba), actual)
            self.model = m
        except Exception as exc:                        # pragma: no cover
            log.warning("확률 보정 적합 실패: %s", exc)
        return self

    def transform(self, proba: np.ndarray) -> np.ndarray:
        if self.model is None:
            return proba
        return self.model.predict_proba(self._logit(proba))[:, 1]

    @property
    def fitted(self) -> bool:
        return self.model is not None


def reliability(proba: np.ndarray, actual: np.ndarray, bins: int = 5) -> dict:
    """신뢰도 곡선. 예측 확률 구간별 실제 상승 비율을 센다.

    잘 보정된 모델이라면 '상승확률 30%' 구간에서 실제로 30% 정도가
    상승해야 한다. 대각선에서 멀수록 확률을 그대로 믿기 어렵다.
    """
    edges = np.linspace(0, 1, bins + 1)
    pred, obs, counts = [], [], []

    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (proba >= lo) & (proba < hi if hi < 1 else proba <= 1)
        if m.sum() < 5:
            continue
        pred.append(round(float(proba[m].mean()) * 100, 1))
        obs.append(round(float(actual[m].mean()) * 100, 1))
        counts.append(int(m.sum()))

    # 평균 절대 보정오차 — 낮을수록 확률을 그대로 믿을 수 있다.
    if pred:
        weights = np.array(counts, dtype=float)
        ece = float(np.average(np.abs(np.array(pred) - np.array(obs)),
                               weights=weights))
    else:
        ece = None

    return {
        "predicted": pred,
        "observed": obs,
        "counts": counts,
        "calibration_error": round(ece, 1) if ece is not None else None,
    }



# ---------------------------------------------------------------- 전체 실행
def build_direction(raw: dict[str, pd.Series], mc: dict | None = None) -> dict:
    """방향 예측 결과 전체. 실패해도 배치를 막지 않도록 dict 를 반환한다."""
    if not HAS_SKLEARN:
        return {"available": False, "reason": "scikit-learn 미설치"}

    px = raw["usdgel"].astype(float)
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

    results, history, oof = {}, {}, {}
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
        oof[name] = (p, a)

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
        raw_prob = float(proba_now[0])
    except Exception as exc:                            # pragma: no cover
        log.warning("현재 시점 예측 실패: %s", exc)
        return {"available": False, "reason": str(exc)}

    # ---- 확률 보정 ----
    # 트리 모델은 확률을 0/1 쪽으로 과하게 밀어낸다. walk-forward 에서 얻은
    # out-of-fold 확률로 보정해야 "상승확률 8%" 같은 과잉 확신이 완화된다.
    flat_share = _flat_share(px)

    p_oof, a_oof = oof[best_name]
    calibrator = PlattCalibrator().fit(p_oof, a_oof)
    up_prob = float(calibrator.transform(np.array([raw_prob]))[0])

    rel_before = reliability(p_oof, a_oof)
    rel_after = reliability(calibrator.transform(p_oof), a_oof)

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
        "raw_up_probability": round(raw_prob * 100, 1),
        "calibrated": calibrator.fitted,
        "calibration": {
            "before": rel_before,
            "after": rel_after,
            "method": "Platt scaling" if calibrator.fitted else "미적용",
            "note": (
                "보정 전후의 적중률은 같습니다. 순서를 바꾸지 않고 확률의 "
                "눈금만 실제 빈도에 맞추기 때문입니다."
            ),
        },
        "flat_share": round(flat_share * 100, 1),
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
        "flat_note": (
            f"검증 구간의 {round(flat_share * 100, 1)}% 는 1개월 변화율이 "
            "0.1% 미만인 사실상 무변동 구간입니다. NBG 개입으로 라리가 "
            "고정되는 날이 많아 생기는 현상이며, 이런 구간도 이진 분류에서는 "
            "상승 또는 하락 한쪽으로 강제 배정됩니다. 비중이 높을수록 "
            "적중률의 의미가 약해집니다."
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

