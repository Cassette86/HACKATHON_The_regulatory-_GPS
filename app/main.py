import streamlit as st
import plotly.express as px
import pandas as pd
from components.styles import card_style
import sys
from pathlib import Path


st.set_page_config(page_title="Dashboard conformité automobile", layout="wide")

st.title("Dashboard de conformité automobile")

# Project-specific import
ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

# -----------------------------
# FAKE DATA
# -----------------------------
country_scores = pd.DataFrame({
    "Pays": ["France", "USA", "Inde", "Brésil", "Allemagne"],
    "Code": ["FRA", "USA", "IND", "BRA", "DEU"],
    "Conformité": [0.92, 0.61, 0.47, 0.52, 0.88]
})

# pays le plus compliant
top_country = country_scores.loc[country_scores["Conformité"].idxmax()]["Pays"]

# -----------------------------
# KPI
# -----------------------------
st.markdown(card_style, unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
        <div class="card">
            <h3>Pays le plus compliant</h3>
            <h1 style="color:#5CB85C;">{top_country}</h1>
        </div>
    """, unsafe_allow_html=True)

with col2:
    avg = round(country_scores["Conformité"].mean() * 100, 1)
    st.markdown(f"""
        <div class="card">
            <h3>Conformité moyenne globale</h3>
            <h1>{avg}%</h1>
        </div>
    """, unsafe_allow_html=True)

# -----------------------------
# CARTE MONDIALE
# -----------------------------
st.subheader("Carte des conformités mondiales")

fig = px.choropleth(
    country_scores,
    locations="Code",
    color="Conformité",
    hover_name="Pays",
    color_continuous_scale=["#D9534F", "#F0AD4E", "#5CB85C"],
    range_color=(0, 1),
    height=450
)

st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# TABLE D'ALERTES
# -----------------------------
st.subheader("Alertes récentes")

alerts = pd.DataFrame({
    "Pays": ["France", "Inde", "USA", "Allemagne"],
    "Conformité": ["92%", "47%", "61%", "88%"],
    "Risques": ["3 tests manquants", "Nouvelle norme non appliquée", "Batterie non certifiée", "RAS"],
    "Action": ["Relancer labo", "Analyse réglementaire", "Mettre en conformité", "—"],
})

st.dataframe(alerts, use_container_width=True)

