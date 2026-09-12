"""국가별 정기예금: 공식 확인 자료와 사용자 환율 가정을 구분한다."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

FILE = Path(__file__).resolve().parent.parent / "deposit_data" / "products.json"


def load_products(path=FILE):
    return json.loads(path.read_text(encoding="utf-8"))


def status(product, checked_on, today=None):
    today = today or date.today()
    if product["rate"] is None:
        return "금리 확인 필요"
    if (today - date.fromisoformat(checked_on)).days > 7:
        return "자료 재확인 필요"
    if product["id"] == "mufg":
        return "과거 공시 · 재확인 필요"
    return "확인일 기준 공시"


def won_return(principal, annual_yield_pct, fx_change_pct):
    """1년 유효 수익률과 원/외화 가치 변화를 결합한 세전 가정 결과."""
    if principal < 0 or annual_yield_pct <= -100 or fx_change_pct <= -100:
        raise ValueError("원금과 수익률·환율 가정을 확인하세요.")
    factor = (1 + annual_yield_pct / 100) * (1 + fx_change_pct / 100)
    return principal * factor, (factor - 1) * 100


def render(selected):
    st.subheader("08 · 국가별 은행 정기예금")
    st.caption("선택한 통화의 현지통화 12개월 정기예금 예시입니다. 전체 은행 목록이나 최고금리 순위가 아니며, 유로화는 독일 상품을 보여줍니다.")
    try:
        data = load_products()
    except (OSError, ValueError):
        st.info("정기예금 자료를 불러올 수 없습니다.")
        return
    products = [p for p in data["products"] if p["code"] in selected]
    st.caption(f"자료 확인일: {data['checked_on']} · {data['update_mode']} · 은행 금리 적용일과 자료 확인일은 다를 수 있습니다.")
    if not products:
        st.info("선택한 통화에 등록된 상품이 없습니다.")
        return
    st.info("명목 연이율·AER·실효금리는 계산 기준이 다릅니다. 외국인·비거주자 가입 여부와 적용금리는 은행에서 확인해야 하며, 높은 예금금리만으로 원화 수익이 보장되지는 않습니다.")
    table = pd.DataFrame([{
        "국가/지역": p["country"], "통화": p["code"], "은행": p["bank"],
        "상품": p["product"], "기간": "12개월", "공시 연금리 (%)": p["rate"],
        "금리 기준": p["basis"], "최소 예치금": p["minimum"],
        "금리 적용/공시일": p["rate_date"] or "원문에 날짜 미표시",
        "확인 상태": status(p, data["checked_on"]), "공식 자료": p["url"],
    } for p in products])
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "공시 연금리 (%)": st.column_config.NumberColumn(format="%.2f"),
        "공식 자료": st.column_config.LinkColumn(display_text="공식 자료 열기"),
    })
    st.caption("빈 금리는 0%가 아니라 미확인입니다. 이 자료는 자동 갱신되지 않으며, 확인 후 7일이 지나면 재확인 상태로 표시합니다.")
    with st.expander("은행별 가입 조건·중도해지", expanded=False):
        for p in products:
            st.markdown(f"**{p['country']} · {p['bank']} ({p['code']})**")
            st.write(p["conditions"])
            st.caption(f"중도해지: {p['early_exit']}")
            st.link_button("공식 상품·금리 확인", p["url"], key=f"deposit-link-{p['id']}")

    with st.expander("예금 이자와 환율을 함께 계산하기 · 1년 가정", expanded=False):
        st.caption("아래 수치는 사용자가 입력하는 가정입니다. 표의 은행 금리를 자동 적용하지 않습니다. 1년 실효 수익률을 입력하세요.")
        a, b, c = st.columns(3)
        principal = a.number_input("계산 원금 (원)", min_value=0.0, value=1000000.0, step=100000.0, key="deposit-principal")
        interest = b.number_input("가정 연수익률 (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1, key="deposit-yield")
        fx = c.number_input("1년 후 외화의 원화 가치 변화 (%)", min_value=-99.0, max_value=300.0, value=0.0, step=1.0, key="deposit-fx")
        total, pct = won_return(principal, interest, fx)
        a, b, c = st.columns(3)
        a.metric("가정 만기 원화 금액", f"{total:,.0f}원")
        b.metric("원화 손익", f"{total-principal:+,.0f}원", f"{pct:+.2f}%")
        c.metric("손익분기 외화 가치 변화", f"{(1/(1+interest/100)-1)*100:.2f}%")
        st.caption("원금 × (1 + 연수익률) × (1 + 외화의 원화 가치 변화). 예: 이자 10%, 외화 가치 -10%이면 원화 수익률 -1%. 원화 예금은 환율 변화를 0%로 입력합니다. 세금·환전/송금 수수료·중도해지 비용은 제외합니다.")
