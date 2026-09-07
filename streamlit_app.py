"""Trading Advisor frontend. Calls the API over httpx only — no business
logic here (PLAYBOOK.md §4a). Screens (trending, symbol detail, analyze
form, dashboard) land in Phase 18; this is just enough to prove the
frontend container can reach the api container.
"""

import os

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Trading Advisor")
st.title("Trading Advisor")
st.caption("Personal market-analysis and monitoring tool — no brokerage account, no execution.")

try:
    response = httpx.get(f"{API_BASE_URL}/health", timeout=5.0)
    response.raise_for_status()
    st.success(f"API reachable at {API_BASE_URL}: {response.json()}")
except httpx.HTTPError as exc:
    st.error(f"API not reachable at {API_BASE_URL}: {exc}")

st.info("Trending / symbol detail / analyze form / dashboard land in Phase 18.")
