"""Круговой индикатор прогресса для Streamlit."""

from __future__ import annotations

import streamlit as st


def render_circular_progress(percent: float, label: str, *, key: str | None = None) -> None:
    pct = max(0.0, min(100.0, percent * 100))
    html = f"""
    <div style="display:flex;align-items:center;gap:20px;margin:12px 0;">
      <div style="
        width:88px;height:88px;border-radius:50%;
        background:conic-gradient(#2563eb {pct}%, #e5e7eb {pct}% 100%);
        display:flex;align-items:center;justify-content:center;
        flex-shrink:0;
      ">
        <div style="
          width:68px;height:68px;border-radius:50%;background:#fff;
          display:flex;align-items:center;justify-content:center;
          font-size:14px;font-weight:600;color:#1f2937;
        ">{pct:.0f}%</div>
      </div>
      <div style="font-size:15px;color:#374151;line-height:1.4;">{label}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
