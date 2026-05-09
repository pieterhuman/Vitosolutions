"""Streamlit CFO dashboard.

Talks to the FastAPI backend at API_BASE. Shows cash, AR/AP, forecast,
recent recommendations, and the approval queue.

Run:
    streamlit run app/ui/dashboard.py
"""

from __future__ import annotations

import os

import httpx
import pandas as pd
import streamlit as st

API_BASE = os.environ.get("CFO_API_BASE", "http://localhost:8000/api")
TENANT = os.environ.get("CFO_TENANT", "demo")
HEADERS = {"X-Tenant-Id": TENANT}

st.set_page_config(page_title="CFO Agents", layout="wide")
st.title("AI CFO Dashboard")


def _get(path: str, **kwargs):
    try:
        r = httpx.get(f"{API_BASE}{path}", headers=HEADERS, timeout=10, **kwargs)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"GET {path} failed: {e}")
        return None


def _post(path: str, **kwargs):
    try:
        r = httpx.post(f"{API_BASE}{path}", headers=HEADERS, timeout=20, **kwargs)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"POST {path} failed: {e}")
        return None


# ---------- Top bar ----------
col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    st.caption(f"Tenant: `{TENANT}` · API: `{API_BASE}`")
with col3:
    if st.button("Run all agents"):
        for task in (
            "RECONCILE_BANK_LINE",
            "BUILD_CASHFLOW_FORECAST",
            "AR_RISK_REVIEW",
            "AP_PAYMENT_PLAN",
            "VAT_RESERVE_CHECK",
            "RESERVE_POLICY_REVIEW",
            "MONTHLY_BOARD_PACK",
        ):
            _post("/agents/dispatch", json={"task_type": task, "inputs": {}})
        st.success("Dispatched.")
        st.rerun()

# ---------- KPI strip ----------
summary = _get("/dashboard/summary") or {}
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Cash", f"{summary.get('cash', 0):,.0f}")
k2.metric("Open AR", f"{summary.get('open_ar', 0):,.0f}", f"overdue {summary.get('overdue_ar', 0):,.0f}")
k3.metric("Open AP", f"{summary.get('open_ap', 0):,.0f}")
k4.metric("Runway (90d)", summary.get("runway_days") or ">90d")
k5.metric("Pending approvals", summary.get("pending_approvals", 0))

st.divider()

# ---------- Forecast chart ----------
st.subheader("Cash flow forecast (90 days)")
fc = _get("/dashboard/forecast/90") or {}
series = fc.get("series", [])
if series:
    df = pd.DataFrame(series)
    df["date"] = pd.to_datetime(df["date"])
    st.line_chart(df.set_index("date")[["balance"]])
    st.caption(fc.get("commentary", ""))
else:
    st.info("No forecast yet — click 'Run all agents'.")

st.divider()

# ---------- Approvals ----------
st.subheader("Approval queue")
approvals = _get("/approvals") or []
if not approvals:
    st.success("Inbox zero. No pending approvals.")
else:
    for a in approvals:
        with st.expander(
            f"[{a['risk']}] {a['agent']}: {a['summary']} (conf {a['confidence']:.2f})"
        ):
            st.json(a["action"])
            c1, c2 = st.columns(2)
            if c1.button("Approve", key=f"ok-{a['id']}"):
                _post(f"/approvals/{a['id']}/approve", json={"note": "via dashboard"})
                st.rerun()
            if c2.button("Reject", key=f"no-{a['id']}"):
                _post(f"/approvals/{a['id']}/reject", json={"note": "via dashboard"})
                st.rerun()

st.divider()

# ---------- Recent recommendations ----------
st.subheader("Recent agent recommendations")
recs = _get("/dashboard/recommendations") or []
if recs:
    df = pd.DataFrame(recs)[["created_at", "agent", "task_type", "summary", "confidence", "risk"]]
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No recommendations yet.")
