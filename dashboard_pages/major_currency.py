"""NBG 교차환율 기반 주요 통화 페이지."""
from __future__ import annotations

import streamlit as st

from gel_app import charts, config, pipeline


def render(code: str, title: str, description: str) -> None:
    snap = pipeline.load_snapshot()
    st.title(title)
    st.caption(description)

    if snap is None:
        st.error("라리화 데이터 스냅샷이 없습니다. GitHub Actions 배치를 실행해 주세요.")
        return

    series = snap.get("crosses", {}).get(code)
    if not series or not series.get("values"):
        st.info("이 통화의 초기 데이터를 준비 중입니다. 라리화 일일 배치가 한 번 실행되면 표시됩니다.")
        return

    values = series["values"]
    digits = series.get("digits", 4)
    latest = values[-1]
    previous = values[-2] if len(values) > 1 else latest
    change = (latest / previous - 1) * 100 if previous else 0

    a, b = st.columns(2)
    a.metric(f"현재 {series['pair']}", f"{latest:,.{digits}f}", f"{change:+.2f}%")
    b.metric("관측치", f"{len(values)}일")

    st.subheader(f"{series['pair']} 추이")
    st.plotly_chart(charts.simple_line(series, charts.C["expert"]), width="stretch", config={"displayModeBar": False})
    st.caption(
        "조지아 국립은행(NBG)의 GEL 기준 고시환율로 계산한 USD 기준 교차환율입니다. "
        f"최종 갱신: {snap.get('meta', {}).get('generated_at_display', '—')} · 캐시: {config.CACHE_TTL // 60}분"
    )
