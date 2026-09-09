"""Plotly 차트 생성기.

모든 함수는 스냅샷의 일부를 받아 Figure 를 반환한다. 연산은 하지 않는다.
"""
from __future__ import annotations

import plotly.graph_objects as go

C = {
    "personal": "#46C9B0",
    "expert": "#E3A94D",
    "risk": "#E2685A",
    "neutral": "#C9D4DE",
    "faint": "#5C7188",
    "grid": "rgba(255,255,255,0.06)",
}


def _base(fig: go.Figure, height: int = 260, legend: bool = False,
          price_axis: bool = False) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=28, t=30 if legend else 8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#8CA0B4", size=11),
        hovermode="x unified",
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=0.99, font=dict(size=10),
                    bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, nticks=6)
    fig.update_yaxes(gridcolor=C["grid"], zeroline=False, nticks=5)
    if price_axis:
        # 라리는 2.67 수준이라 기본 포맷으로는 눈금이 2.7 처럼 뭉개진다.
        fig.update_yaxes(tickformat=".3f")
    return fig


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------- 개인용
def history(d: dict) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=d["labels"], y=d["values"], mode="lines", name="USD/KRW",
        line=dict(color=C["personal"], width=2),
        fill="tozeroy", fillcolor=_rgba(C["personal"], 0.08),
    ))
    fig.update_yaxes(range=[min(d["values"]) * 0.97, max(d["values"]) * 1.03])
    return _base(fig, price_axis=True)


def scenario(hist: dict, sc: dict) -> go.Figure:
    """과거는 실선, 미래는 3개 시나리오 점선 + 밴드."""
    fig = go.Figure()
    bridge_x = [hist["labels"][-1]] + sc["labels"]

    fig.add_trace(go.Scatter(
        x=bridge_x, y=[sc["anchor"]] + sc["bear"], name="약세",
        mode="lines", line=dict(color=C["risk"], width=2, dash="dash"),
    ))
    fig.add_trace(go.Scatter(
        x=bridge_x, y=[sc["anchor"]] + sc["bull"], name="강세",
        mode="lines", line=dict(color=C["personal"], width=2, dash="dash"),
        fill="tonexty", fillcolor="rgba(120,150,170,0.10)",
    ))
    fig.add_trace(go.Scatter(
        x=bridge_x, y=[sc["anchor"]] + sc["base"], name="중립",
        mode="lines", line=dict(color=C["expert"], width=2, dash="dash"),
    ))
    fig.add_trace(go.Scatter(
        x=hist["labels"], y=hist["values"], name="실제",
        mode="lines", line=dict(color=C["neutral"], width=2),
    ))
    return _base(fig, height=330, legend=True, price_axis=True)


def bollinger(d: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["labels"], y=d["upper"], name="상단",
                             mode="lines", line=dict(color=_rgba(C["expert"], 0.4), width=1)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["lower"], name="하단",
                             mode="lines", line=dict(color=_rgba(C["expert"], 0.4), width=1),
                             fill="tonexty", fillcolor=_rgba(C["expert"], 0.07)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["ma"], name="20일 이동평균",
                             mode="lines", line=dict(color=C["expert"], width=2)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["price"], name="종가",
                             mode="lines", line=dict(color=C["neutral"], width=1.5)))
    return _base(fig, price_axis=True)


# ---------------------------------------------------------------- 공통
def simple_line(d: dict, color: str, fill: bool = False) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=d["labels"], y=d["values"], mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy" if fill else None,
        fillcolor=_rgba(color, 0.08) if fill else None,
    ))
    if fill:
        fig.update_yaxes(range=[min(d["values"]) * 0.9, max(d["values"]) * 1.1])
    return _base(fig, height=220)


def signed_bar(d: dict) -> go.Figure:
    colors = [C["personal"] if v >= 0 else C["risk"] for v in d["values"]]
    fig = go.Figure(go.Bar(x=d["labels"], y=d["values"], marker_color=colors))
    return _base(fig, height=220)


# ---------------------------------------------------------------- 전문가용
def garch(d: dict) -> go.Figure:
    hist_x = d["history_labels"][-60:]
    hist_y = d["history"][-60:]
    fc_x = [f"+{i+1}D" for i in range(len(d["forecast"]))]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist_x, y=hist_y, name="실현 변동성",
                             mode="lines", line=dict(color=C["neutral"], width=1.5)))
    fig.add_trace(go.Scatter(x=[hist_x[-1]] + fc_x, y=[hist_y[-1]] + d["forecast"],
                             name=d["method"], mode="lines",
                             line=dict(color=C["expert"], width=2, dash="dash")))
    return _base(fig, height=220, legend=True)


def monte_carlo(d: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["labels"], y=d["p95"], name="95%",
                             mode="lines", line=dict(color="rgba(70,201,176,0.25)", width=1)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["p75"], name="75%",
                             mode="lines", line=dict(color="rgba(70,201,176,0.35)", width=1),
                             fill="tonexty", fillcolor=_rgba(C["personal"], 0.07)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["p25"], name="25%",
                             mode="lines", line=dict(color="rgba(70,201,176,0.35)", width=1),
                             fill="tonexty", fillcolor=_rgba(C["personal"], 0.13)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["p05"], name="5%",
                             mode="lines", line=dict(color="rgba(70,201,176,0.25)", width=1),
                             fill="tonexty", fillcolor=_rgba(C["personal"], 0.07)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["p50"], name="중앙값",
                             mode="lines", line=dict(color=C["personal"], width=2)))
    return _base(fig, height=240, price_axis=True)


def interval(d: dict) -> go.Figure:
    """ARIMA / BSTS 신뢰구간."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["labels"], y=d["upper"], name="상한",
                             mode="lines", line=dict(color=_rgba(C["expert"], 0.3), width=1)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["lower"], name="하한",
                             mode="lines", line=dict(color=_rgba(C["expert"], 0.3), width=1),
                             fill="tonexty", fillcolor=_rgba(C["expert"], 0.09)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["mean"], name=d["method"],
                             mode="lines", line=dict(color=C["expert"], width=2, dash="dot")))
    return _base(fig, height=220, price_axis=True)


def impulse(d: dict) -> go.Figure:
    base = d["mean"][0]
    fig = go.Figure(go.Scatter(
        x=d["labels"], y=[round(v - base, 2) for v in d["mean"]],
        mode="lines", line=dict(color=C["expert"], width=2, shape="spline"),
    ))
    fig.add_hline(y=0, line=dict(color=C["faint"], width=1, dash="dot"))
    return _base(fig, height=220)


def backtest(d: dict) -> go.Figure:
    colors = [C["personal"]] + [C["faint"]] * (len(d["labels"]) - 1)
    fig = go.Figure(go.Bar(
        x=d["rmse"][::-1], y=d["labels"][::-1], orientation="h",
        marker_color=colors[::-1],
        text=[f"{v:.1f}" for v in d["rmse"][::-1]], textposition="outside",
        textfont=dict(size=10),
    ))
    fig.update_xaxes(title_text="RMSE (낮을수록 정확)", title_font=dict(size=10))
    fig.update_yaxes(type="category", tickmode="array",
                     tickvals=d["labels"], nticks=0)
    return _base(fig, height=max(240, 34 * len(d["labels"])))


def importance(d: dict) -> go.Figure:
    imp = d.get("importance", {})
    items = sorted(imp.items(), key=lambda kv: kv[1])
    fig = go.Figure(go.Bar(
        x=[v * 100 for _, v in items], y=[k for k, _ in items], orientation="h",
        marker_color=C["personal"],
        text=[f"{v*100:.1f}%" for _, v in items], textposition="outside",
        textfont=dict(size=10),
    ))
    fig.update_xaxes(range=[0, 100], ticksuffix="%")
    # 가로 막대에서는 모든 항목명이 보여야 한다(기본 nticks 로는 잘린다).
    fig.update_yaxes(type="category", tickmode="array",
                     tickvals=[k for k, _ in items], nticks=0)
    return _base(fig, height=max(220, 34 * len(items)))


def heatmap(d: dict) -> go.Figure:
    fig = go.Figure(go.Heatmap(
        z=d["matrix"], x=d["assets"], y=d["assets"],
        colorscale=[[0, C["risk"]], [0.5, "#1B2A3A"], [1, C["personal"]]],
        zmid=0, zmin=-1, zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in d["matrix"]],
        texttemplate="%{text}", textfont=dict(size=10),
        showscale=False,
    ))
    return _base(fig, height=260)


def tail_risk(d: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["labels"], y=d["var95"], name="VaR 95%",
                         marker_color=_rgba(C["expert"], 0.8)))
    fig.add_trace(go.Bar(x=d["labels"], y=d["cvar99"], name="CVaR 99%",
                         marker_color=_rgba(C["risk"], 0.8)))
    fig.update_layout(barmode="group")
    return _base(fig, height=220, legend=True)


def decomposition(d: dict) -> go.Figure:
    palette = [C["expert"], C["personal"], C["risk"]]
    fig = go.Figure()
    for i, (name, vals) in enumerate(d["series"].items()):
        fig.add_trace(go.Bar(x=d["labels"], y=vals, name=name,
                             marker_color=palette[i % 3]))
    fig.update_layout(barmode="relative")
    fig.update_xaxes(nticks=8)
    return _base(fig, height=240, legend=True)


def events(hist: dict, marks=(2, 5, 8)) -> go.Figure:
    x = hist["labels"][-12:]
    y = hist["values"][-12:]
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines",
                               line=dict(color=C["neutral"], width=2)))
    fig.add_trace(go.Scatter(
        x=[x[i] for i in marks if i < len(x)],
        y=[y[i] for i in marks if i < len(y)],
        mode="markers", name="주요 이벤트",
        marker=dict(color=C["expert"], size=9, line=dict(color="#0B1420", width=2)),
    ))
    return _base(fig, height=220)


# ---------------------------------------------------------------- 방향 예측
def reliability_curve(cal: dict) -> go.Figure:
    """신뢰도 곡선. 대각선에 가까울수록 확률을 그대로 믿을 수 있다."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[0, 100], y=[0, 100], name="이상적", mode="lines",
        line=dict(color=C["faint"], width=1, dash="dot"),
    ))
    before, after = cal.get("before", {}), cal.get("after", {})
    if before.get("predicted"):
        fig.add_trace(go.Scatter(
            x=before["predicted"], y=before["observed"], name="보정 전",
            mode="lines+markers", line=dict(color=C["risk"], width=2),
            marker=dict(size=7),
        ))
    if after.get("predicted"):
        fig.add_trace(go.Scatter(
            x=after["predicted"], y=after["observed"], name="보정 후",
            mode="lines+markers", line=dict(color=C["personal"], width=2),
            marker=dict(size=7),
        ))
    fig.update_xaxes(title_text="예측 확률", ticksuffix="%", range=[0, 100],
                     title_font=dict(size=10))
    fig.update_yaxes(title_text="실제 상승 비율", ticksuffix="%", range=[0, 100],
                     title_font=dict(size=10))
    return _base(fig, height=240, legend=True)


def proba_history(d: dict) -> go.Figure:
    """모델별 상승확률 추이. 50% 기준선을 함께 그린다."""
    palette = {"LightGBM": C["personal"], "로지스틱 회귀": C["expert"]}
    fig = go.Figure()
    for name, h in d["history"].items():
        fig.add_trace(go.Scatter(
            x=h["labels"], y=h["proba"], name=name, mode="lines",
            line=dict(color=palette.get(name, C["faint"]), width=1.8),
        ))
    fig.add_hline(y=50, line=dict(color=C["faint"], width=1, dash="dot"))
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    return _base(fig, height=220, legend=True)


def confusion(m: dict) -> go.Figure:
    """혼동행렬. 대각선이 맞힌 경우다."""
    c = m["confusion"]
    z = [[c["tn"], c["fp"]], [c["fn"], c["tp"]]]
    fig = go.Figure(go.Heatmap(
        z=z, x=["하락 예측", "상승 예측"], y=["실제 하락", "실제 상승"],
        colorscale=[[0, "#1B2A3A"], [1, C["personal"]]],
        text=[[str(v) for v in row] for row in z],
        texttemplate="%{text}", textfont=dict(size=14),
        showscale=False,
    ))
    return _base(fig, height=220)


def model_compare(metrics: dict) -> go.Figure:
    """적중률을 기준선과 나란히 놓아야 우위 여부가 보인다."""
    names = list(metrics.keys())
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=names, y=[metrics[n]["accuracy"] for n in names], name="적중률",
        marker_color=C["personal"],
        text=[f"{metrics[n]['accuracy']}%" for n in names],
        textposition="outside", textfont=dict(size=10),
    ))
    fig.add_trace(go.Bar(
        x=names, y=[metrics[n]["balanced_accuracy"] for n in names],
        name="균형 정확도", marker_color=C["expert"],
    ))
    fig.add_trace(go.Bar(
        x=names, y=[metrics[n]["baseline"] for n in names],
        name="기준선", marker_color=C["faint"],
    ))
    fig.update_layout(barmode="group")
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    return _base(fig, height=240, legend=True)


def tracking_history(t: dict) -> go.Figure:
    """기록된 예측과 실제값 대조."""
    rec = [r for r in t.get("recent", []) if r.get("forecast") is not None]
    if not rec:
        return _base(go.Figure(), height=200)

    x = [r["date"] for r in rec]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=[r["spot"] for r in rec], name="예측 시점 환율",
        mode="lines+markers", line=dict(color=C["neutral"], width=1.8),
        marker=dict(size=5),
    ))
    fig.add_trace(go.Scatter(
        x=x, y=[r["forecast"] for r in rec], name="1개월 예측",
        mode="lines+markers", line=dict(color=C["expert"], width=1.8, dash="dash"),
        marker=dict(size=5),
    ))
    actual = [r.get("actual") for r in rec]
    if any(a is not None for a in actual):
        fig.add_trace(go.Scatter(
            x=x, y=actual, name="실제값", mode="markers",
            marker=dict(color=C["personal"], size=8, symbol="diamond"),
        ))
    return _base(fig, height=220, legend=True)


# ---------------------------------------------------------------- 라리 전용
def seasonal_decomp(d: dict) -> go.Figure:
    """STL 분해 결과 — 추세와 계절 성분을 겹쳐 본다."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["labels"], y=d["observed"], name="실제",
                             mode="lines", line=dict(color=C["neutral"], width=1.5)))
    fig.add_trace(go.Scatter(x=d["labels"], y=d["trend"], name="추세",
                             mode="lines", line=dict(color=C["personal"], width=2)))
    return _base(fig, height=230, legend=True)


def month_effect(d: dict) -> go.Figure:
    """월별 평균 계절 효과. 양수면 그 달에 라리가 약세(환율 상승)."""
    vals = d["month_effect"]
    colors = [C["risk"] if v >= 0 else C["personal"] for v in vals]
    fig = go.Figure(go.Bar(x=d["month_labels"], y=vals, marker_color=colors))
    fig.add_hline(y=0, line=dict(color=C["faint"], width=1))
    return _base(fig, height=230)


def peer_currencies(peers: dict) -> go.Figure:
    """지역 통화들을 1년 전 대비 변화율로 겹쳐 그린다.

    단위가 제각각이므로 수준이 아니라 변화율로 비교해야 의미가 있다.
    """
    palette = [C["personal"], C["expert"], C["risk"], "#7FA8D9", "#B48EAD"]
    fig = go.Figure()
    for i, (name, series) in enumerate(peers.items()):
        fig.add_trace(go.Scatter(
            x=series["labels"], y=series["values"], name=name, mode="lines",
            line=dict(color=palette[i % len(palette)], width=1.8),
        ))
    fig.add_hline(y=0, line=dict(color=C["faint"], width=1, dash="dot"))
    fig.update_yaxes(ticksuffix="%")
    return _base(fig, height=250, legend=True)


def dual_line(a: dict, b: dict, name_a: str, name_b: str) -> go.Figure:
    """두 지표를 각각의 축에 그린다(단위가 다를 때)."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=a["labels"], y=a["values"], name=name_a,
                             mode="lines", line=dict(color=C["personal"], width=2)))
    fig.add_trace(go.Scatter(x=b["labels"], y=b["values"], name=name_b,
                             mode="lines", yaxis="y2",
                             line=dict(color=C["expert"], width=2)))
    fig.update_layout(yaxis2=dict(overlaying="y", side="right",
                                  showgrid=False, tickfont=dict(size=10)))
    return _base(fig, height=230, legend=True)

