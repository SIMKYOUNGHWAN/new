"""환율 대시보드 페이지 탐색."""
import streamlit as st

st.set_page_config(page_title="환율 대시보드", page_icon="💱", layout="wide", initial_sidebar_state="expanded")

navigation = st.navigation([
    st.Page("dashboard_pages/overview.py", title="글로벌 환율 종합", icon="🌐"),
    st.Page("dashboard_pages/schd.py", title="SCHD 미국 배당주", icon="📈"),
    st.Page("dashboard_pages/krw.py", title="대한민국 원화", icon="🇰🇷", default=True),
    st.Page("dashboard_pages/gel.py", title="조지아 라리화", icon="🇬🇪"),
    st.Page("dashboard_pages/cny.py", title="중국 위안화", icon="🇨🇳"),
    st.Page("dashboard_pages/eur.py", title="유럽 유로화", icon="🇪🇺"),
    st.Page("dashboard_pages/gbp.py", title="영국 파운드화", icon="🇬🇧"),
    st.Page("dashboard_pages/jpy.py", title="일본 엔화", icon="🇯🇵"),
    st.Page("dashboard_pages/try_currency.py", title="터키 리라", icon="🇹🇷", url_path="try"),
])
st.sidebar.caption("라리: NBG 공식 환율 · 주요 5통화: ECB 기준환율")
navigation.run()




