"""가격 기반 검증·위험 분석. 공표 시차가 불명확한 거시자료는 학습에서 제외."""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss, confusion_matrix
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from . import analytics


def walk_forward(px):
    m = analytics.monthly(px)
    if px.index[-1].day != px.index[-1].days_in_month:
        m = m.iloc[:-1]
    predictions = {"랜덤워크": [], "6개월 이동평균": [], "드리프트": []}
    actual = []
    for i in range(max(24, len(m) - 12), len(m)):
        train = m.iloc[:i]
        predictions["랜덤워크"].append(float(train.iloc[-1]))
        predictions["6개월 이동평균"].append(float(train.tail(6).mean()))
        predictions["드리프트"].append(float(train.iloc[-1] + train.diff().tail(12).mean()))
        actual.append(float(m.iloc[i]))
    return {"labels": list(predictions), "rmse": [float(np.sqrt(np.mean((np.array(p) - actual) ** 2))) for p in predictions.values()],
            "test_months": len(actual), "method": "월별 1단계 확장 학습 (walk-forward)"}


def direction(px):
    horizon = 20
    returns = np.log(px / px.shift(1))
    features = pd.DataFrame({
        "5관측일 수익률": px.pct_change(5), "20관측일 수익률": px.pct_change(20),
        "60관측일 수익률": px.pct_change(60), "20관측일 변동성": returns.rolling(20).std(),
        "이동평균 이격": px / px.rolling(60).mean() - 1,
    }).dropna()
    future = px.shift(-horizon)
    y = (future > px).where(future.notna()).reindex(features.index)
    model = lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=1000))
    actual, probabilities, baselines, dates = [], [], [], []
    # Non-overlapping validation targets; purge the entire forecast horizon.
    for i in range(max(300, len(features) - 240), len(features) - horizon, horizon):
        train_x, train_y = features.iloc[:i-horizon], y.iloc[:i-horizon]
        if train_y.nunique() < 2:
            continue
        fitted = model().fit(train_x, train_y.astype(int))
        probabilities.append(float(fitted.predict_proba(features.iloc[[i]])[0, 1]))
        actual.append(int(y.iloc[i]))
        baselines.append(int(train_y.mean() >= 0.5))
        dates.append(features.index[i].strftime("%Y-%m-%d"))
    known = y.notna()
    if not actual or y[known].nunique() < 2:
        return {"available": False, "reason": "검증 표본 또는 상승·하락 사례 부족"}
    fitted = model().fit(features[known], y[known].astype(int))
    probability = float(fitted.predict_proba(features.tail(1))[0, 1])
    predicted = np.array(probabilities) >= 0.5
    bins = []
    probs, actual_array = np.array(probabilities), np.array(actual)
    for lo, hi in ((0, .25), (.25, .5), (.5, .75), (.75, 1.01)):
        mask = (probs >= lo) & (probs < hi)
        if mask.any():
            bins.append({"예측확률 평균": float(probs[mask].mean()*100),
                         "실제 상승 비율": float(actual_array[mask].mean()*100), "표본": int(mask.sum())})
    return {"available": True, "up_probability": round(probability*100, 1),
            "accuracy": round(accuracy_score(actual, predicted)*100, 1),
            "balanced_accuracy": round(balanced_accuracy_score(actual, predicted)*100, 1),
            "baseline": round(accuracy_score(actual, baselines)*100, 1),
            "brier": round(brier_score_loss(actual, probabilities), 4),
            "n": len(actual), "confusion": confusion_matrix(actual, predicted, labels=[0,1]).tolist(),
            "labels": dates, "probabilities": [round(p*100, 1) for p in probabilities],
            "coefficients": dict(zip(features.columns, fitted[-1].coef_[0].round(4).tolist())),
            "reliability": bins, "horizon": horizon}


def forecast20(px):
    ret = np.log(px / px.shift(1)).dropna()
    rng = np.random.default_rng(2026)
    paths = float(px.iloc[-1]) * np.exp(rng.normal(float(ret.mean()), float(ret.std()), (5000, 20)).sum(axis=1))
    return {k: round(float(np.quantile(paths, q)), 4) for k, q in (("lower", .05), ("median", .5), ("upper", .95))}


def risk(px):
    r = px.pct_change(20).dropna()
    q = float(r.quantile(.95))
    return {"var95_pct": round(q*100, 3), "cvar95_pct": round(float(r[r >= q].mean())*100, 3),
            "sample_size": len(r), "max_drawdown_pct": round(float((px / px.cummax() - 1).min())*100, 3)}

