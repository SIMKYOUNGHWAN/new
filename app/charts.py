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


def _base(fig: go.Figure, height: int = 260, legend: bool = False) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=20 if legend else 8, t=30 if legend else 8, b=8),
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
    return _base(fig)


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
    return _base(fig, height=330, legend=True)


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
    return _base(fig)


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
    return _base(fig, height=240)


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
    return _base(fig, height=220)


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
    return _base(fig, height=240)


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
    return _base(fig, height=220)


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
