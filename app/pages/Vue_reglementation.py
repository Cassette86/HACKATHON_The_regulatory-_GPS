import streamlit as st
import pandas as pd
import plotly.express as px
from components.styles import card_style

st.title("Vue par réglementation")

st.markdown(card_style, unsafe_allow_html=True)

# ----------------------------------
# Données fictives
# ----------------------------------
data = pd.DataFrame({
    "Pays": ["France", "France", "France", "USA", "USA", "Inde", "Inde"],
    "Pièce": ["Airbag", "Batterie", "ABS", "Airbag", "Batterie", "ABS", "Éclairage"],
    "Réf": ["AB-442", "BT-901", "ABS-02", "AB-442", "BT-901", "ABS-02", "EL-88"],
    "Norme": [
        "ISO 26262", "Directive 2009/48/CE", "UNECE R13",
        "FMVSS 208", "UL 2580", "AIS-150", "AIS-008"
    ],
    "Conformité": [92, 81, 77, 61, 45, 52, 88]
})

# ----------------------------------
# Sélection du pays
# ----------------------------------
pays = st.selectbox("Sélection du pays :", sorted(data["Pays"].unique()))

df_country = data[data["Pays"] == pays]

# ----------------------------------
# Tableau
# ----------------------------------
st.markdown("### Pièces & Réglementations associées")
st.dataframe(df_country, use_container_width=True)

# ----------------------------------
# Statistiques de fin page
# ----------------------------------
st.markdown("### Statistiques du pays sélectionné")

moy = round(df_country["Conformité"].mean(), 2)
nb_low = df_country[df_country["Conformité"] < 60].shape[0]

col1, col2 = st.columns(2)

with col1:
    st.markdown(f"""
        <div class="card">
            <h4>Conformité moyenne</h4>
            <h2>{moy}%</h2>
        </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
        <div class="card">
            <h4>Pièces à risque</h4>
            <h2>{nb_low}</h2>
        </div>
    """, unsafe_allow_html=True)

# ----------------------------------
# Graphique
# ----------------------------------
st.markdown("### Distribution des conformités")

fig = px.bar(
    df_country,
    x="Pièce",
    y="Conformité",
    color="Conformité",
    color_continuous_scale=["#D9534F", "#F0AD4E", "#5CB85C"],
    height=400
)

st.plotly_chart(fig, use_container_width=True)
