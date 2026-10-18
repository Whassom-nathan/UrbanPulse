from pathlib import Path
import zipfile
import urllib.request
import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

# =========================================================
# URBANPULSE — Data storytelling mobilité & qualité de l'air
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
GTFS_PATH = DATA_DIR / "transport_gtfs.zip"
AIR_PATH = DATA_DIR / "air_quality.csv"

GTFS_URL = (
    "https://github.com/Whassom-nathan/UrbanPulse/"
    "releases/download/v1.0-data/transport_gtfs.zip"
)


def ensure_gtfs_file():
    """Télécharge l'archive GTFS si elle n'est pas déjà présente."""
    if GTFS_PATH.exists():
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = GTFS_PATH.with_suffix(".zip.part")

    try:
        with st.spinner("Téléchargement des données de transport (environ 150 Mo)…"):
            request = urllib.request.Request(
                GTFS_URL,
                headers={"User-Agent": "UrbanPulse-Streamlit"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                with open(temporary_path, "wb") as destination:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        destination.write(chunk)

        # Vérifie l'archive avant de la conserver.
        with zipfile.ZipFile(temporary_path, "r") as archive:
            if "stops.txt" not in archive.namelist():
                raise ValueError("L'archive ne contient pas stops.txt.")
            if "routes.txt" not in archive.namelist():
                raise ValueError("L'archive ne contient pas routes.txt.")

        temporary_path.replace(GTFS_PATH)

    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


st.set_page_config(
    page_title="UrbanPulse | Mobilité & qualité de l'air",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.4rem; padding-bottom: 2.8rem; max-width: 1500px;}
    .hero {
        padding: 1.7rem 1.9rem; border-radius: 18px;
        background: linear-gradient(115deg, #102a43 0%, #176b72 100%);
        color: #ffffff; margin-bottom: 1rem;
    }
    .hero h1 {font-size: 2.35rem; margin: 0 0 .35rem 0;}
    .hero p {font-size: 1.02rem; margin: 0; opacity: .94;}
    .story {
        border-left: 4px solid #168b86; padding: .6rem 1rem;
        background: rgba(22,139,134,.08); border-radius: 0 10px 10px 0;
        margin: .4rem 0 1rem 0;
    }
    div[data-testid="stMetric"] {
        background: rgba(128,128,128,.07); padding: 13px 15px;
        border-radius: 12px; border: 1px solid rgba(128,128,128,.18);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------- Data loading -----------------------------
@st.cache_data(show_spinner="Chargement du réseau de transport…")
def load_gtfs(zip_path: str, modified_time: float):
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open("stops.txt") as file:
            stops = pd.read_csv(file, low_memory=False)
        with archive.open("routes.txt") as file:
            routes = pd.read_csv(file, low_memory=False)

    required_stops = {"stop_lat", "stop_lon", "stop_name"}
    missing = required_stops - set(stops.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes dans stops.txt : {', '.join(sorted(missing))}")

    for col in ["stop_lat", "stop_lon"]:
        stops[col] = pd.to_numeric(stops[col], errors="coerce")
    stops = stops.dropna(subset=["stop_lat", "stop_lon"]).copy()
    # Emprise géographique indicative de l'Île-de-France.
    stops = stops[
        stops["stop_lat"].between(48.0, 49.3)
        & stops["stop_lon"].between(1.4, 3.6)
    ].copy()
    stops["stop_name"] = stops["stop_name"].fillna("Arrêt sans nom").astype(str)
    if "stop_id" in stops.columns:
        stops["stop_id"] = stops["stop_id"].astype(str)

    if "route_type" not in routes.columns:
        routes["route_type"] = pd.NA
    routes["route_type"] = pd.to_numeric(routes["route_type"], errors="coerce")
    for col in ["route_short_name", "route_long_name"]:
        if col not in routes.columns:
            routes[col] = pd.NA
    routes["route_short_name"] = (
        routes["route_short_name"].fillna(routes["route_long_name"]).fillna("Sans nom").astype(str)
    )
    routes["route_long_name"] = routes["route_long_name"].fillna("")

    type_names = {
        0: "Tramway", 1: "Métro", 2: "Train / RER", 3: "Bus",
        4: "Bateau", 5: "Tramway (type 5)", 6: "Téléphérique",
        7: "Funiculaire",
    }
    routes["type_transport"] = routes["route_type"].map(type_names).fillna("Type non documenté")
    return stops, routes


@st.cache_data(show_spinner="Chargement des données de qualité de l'air…")
def load_air_quality(csv_path: str, modified_time: float):
    air = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig")
    air.columns = air.columns.str.strip()
    if "Année" not in air.columns:
        raise ValueError("La colonne « Année » est introuvable dans air_quality.csv.")
    air["Année"] = pd.to_numeric(air["Année"], errors="coerce")
    air = air.dropna(subset=["Année"]).copy()
    air["Année"] = air["Année"].astype(int)
    for col in air.columns:
        if col != "Année":
            # Tolérer les décimales avec virgule, si présentes.
            if air[col].dtype == "object":
                air[col] = air[col].astype(str).str.replace(",", ".", regex=False)
            air[col] = pd.to_numeric(air[col], errors="coerce")
    return air.sort_values("Année").reset_index(drop=True)


def short_label(column: str) -> str:
    """Rendre les intitulés de colonnes plus lisibles sans inventer d'unité."""
    text = column
    for phrase in [
        "Fond-urbain Moyenne annuelle - Airparif",
        "Moyenne annuelle - Airparif",
        "Moyenne annuelle",
        "Concentration moyenne",
        "Fond-urbain",
        "Airparif",
    ]:
        text = text.replace(phrase, "")
    text = text.replace("_", " ").strip(" -")
    return text or column


def is_variation_column(column: str) -> bool:
    lowered = column.lower()
    return "variation" in lowered or "evolution" in lowered or "évolution" in lowered


def display_num(value, digits=1):
    if pd.isna(value):
        return "N/D"
    return f"{value:,.{digits}f}".replace(",", " ")


def pct_change(first, last):
    if pd.isna(first) or pd.isna(last) or first == 0:
        return None
    return (last - first) / abs(first) * 100


# ----------------------------- File checks -----------------------------
try:
    ensure_gtfs_file()
except Exception as exc:
    st.error(f"Impossible de télécharger les données GTFS : {exc}")
    st.info("Vérifie le lien de la release GitHub et réessaie.")
    st.stop()
missing_files = [p for p in [GTFS_PATH, AIR_PATH] if not p.exists()]
if missing_files:
    st.error("Certains fichiers de données sont introuvables :")
    for path in missing_files:
        st.code(str(path))
    st.info("Vérifie que les fichiers sont bien placés dans le dossier `data/`.")
    st.stop()

try:
    stops, routes = load_gtfs(str(GTFS_PATH), GTFS_PATH.stat().st_mtime)
    air = load_air_quality(str(AIR_PATH), AIR_PATH.stat().st_mtime)
except Exception as exc:
    st.error(f"Impossible de charger les données : {exc}")
    st.stop()

if stops.empty or routes.empty or air.empty:
    st.warning("Au moins un jeu de données est vide après chargement ou nettoyage.")

# Measurement columns: numeric annual indicators, excluding precomputed variations.
measurement_columns = [
    c for c in air.columns
    if c != "Année" and not is_variation_column(c) and air[c].notna().any()
]
if not measurement_columns:
    st.error("Aucun indicateur numérique exploitable n'a été détecté dans le CSV.")
    st.stop()

# Prefer a NO2 annual mean where possible.
no2_candidates = [
    c for c in measurement_columns
    if "no2" in c.lower() and ("moyenne annuelle" in c.lower() or "annuelle" in c.lower())
]
default_measure = no2_candidates[0] if no2_candidates else measurement_columns[0]
years = sorted(air["Année"].unique().tolist())

# ----------------------------- Sidebar controls -----------------------------
st.sidebar.title("🌍 UrbanPulse")
st.sidebar.caption("Comprendre les tendances, pas seulement afficher des chiffres.")
st.sidebar.subheader("Filtres d'analyse")
if len(years) > 1:
    selected_years = st.sidebar.slider(
        "Période de qualité de l'air",
        min_value=int(min(years)),
        max_value=int(max(years)),
        value=(int(min(years)), int(max(years))),
        step=1,
    )
else:
    selected_years = (int(years[0]), int(years[0]))

selected_measure = st.sidebar.selectbox(
    "Indicateur principal",
    options=measurement_columns,
    index=measurement_columns.index(default_measure),
    format_func=short_label,
    help="Les colonnes identifiées comme variations sont exclues.",
)
transport_types = sorted(routes["type_transport"].dropna().unique().tolist())
selected_types = st.sidebar.multiselect(
    "Types de transport",
    options=transport_types,
    default=transport_types,
)
map_mode = st.sidebar.radio(
    "Vue de la carte",
    ["Points des arrêts", "Densité spatiale"],
    help="La densité résume les concentrations de points ; elle ne représente pas la fréquentation.",
)
st.sidebar.caption(
    "Le filtre temporel concerne les mesures annuelles d'air. "
    "Le filtre transport concerne les statistiques du fichier des lignes."
)

air_f = air[air["Année"].between(selected_years[0], selected_years[1])].copy()
routes_f = routes[routes["type_transport"].isin(selected_types)].copy()
series = air_f[["Année", selected_measure]].dropna().sort_values("Année")
short_measure = short_label(selected_measure)

# ----------------------------- Hero and story arc -----------------------------
st.markdown(
    """
    <div class="hero">
      <h1>🌍 UrbanPulse</h1>
      <p>Mobilité en Île-de-France & évolution de la qualité de l'air</p>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    "**Question directrice :** l'évolution de la qualité de l'air et la structure du réseau de transport "
    "permettent-elles d'identifier des tendances utiles pour la planification urbaine ?"
)
st.caption(
    "Sources : réseau GTFS d'Île-de-France Mobilités et mesures annuelles de qualité de l'air. "
    "Analyse descriptive : les deux sources ne sont pas alignées au même niveau géographique et temporel."
)

tabs = st.tabs([
    "01 · Diagnostic",
    "02 · Tendances de l'air",
    "03 · Géographie du réseau",
    "04 · Comparaisons",
    "05 · Qualité des données",
    "06 · Conclusions",
])

# ----------------------------- 01 Diagnostic -----------------------------
with tabs[0]:
    st.subheader("01 — Le diagnostic en un coup d'œil")
    st.markdown(
        '<div class="story"><b>À lire :</b> commencer par l’échelle du réseau, puis examiner '
        'la tendance de l’indicateur choisi. Ces chiffres décrivent les données disponibles, '
        'pas la fréquentation réelle des transports.</div>',
        unsafe_allow_html=True,
    )
    latest = series.iloc[-1] if not series.empty else None
    first = series.iloc[0] if not series.empty else None
    delta = pct_change(first[selected_measure], latest[selected_measure]) if first is not None and latest is not None else None

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Arrêts géolocalisés", f"{len(stops):,}".replace(",", " "))
    k2.metric("Lignes dans le filtre", f"{len(routes_f):,}".replace(",", " "))
    k3.metric("Années observées", str(air_f["Année"].nunique()))
    k4.metric(
        f"{short_measure} · dernière année",
        display_num(latest[selected_measure], 2) if latest is not None else "N/D",
        delta=(f"{delta:+.1f} % depuis {int(first['Année'])}" if delta is not None else None),
        delta_color="inverse" if delta is not None else "normal",
        help="Variation calculée entre la première et la dernière observation non manquante de la période filtrée. Elle ne prouve pas une causalité.",
    )

    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("#### Où se trouve l'offre de transport dans le fichier ?")
        if routes_f.empty:
            st.info("Aucune ligne ne correspond aux types de transport sélectionnés.")
        else:
            mode_counts = routes_f.groupby("type_transport").size().reset_index(name="Enregistrements de lignes")
            mode_counts = mode_counts.sort_values("Enregistrements de lignes", ascending=False)
            fig = px.bar(
                mode_counts, x="type_transport", y="Enregistrements de lignes",
                color="type_transport", text="Enregistrements de lignes",
                labels={"type_transport": "Type de transport", "Enregistrements de lignes": "Lignes répertoriées"},
                title="Répartition des lignes par type",
                template="plotly_white",
            )
            fig.update_layout(showlegend=False, xaxis_title="", margin=dict(l=10, r=10, t=55, b=10))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Il s'agit du nombre d'enregistrements de lignes GTFS, pas du nombre de trajets ni de la capacité.")
    with right:
        st.markdown("#### La tendance de l'indicateur choisi")
        if series.empty:
            st.info("Pas de valeurs pour l'indicateur et la période sélectionnés.")
        else:
            fig = px.line(
                series, x="Année", y=selected_measure, markers=True,
                labels={"Année": "Année", selected_measure: short_measure},
                title=short_measure, template="plotly_white",
            )
            fig.update_traces(hovertemplate="Année : %{x}<br>Valeur source : %{y:.3f}<extra></extra>")
            fig.update_layout(xaxis=dict(dtick=1), margin=dict(l=10, r=10, t=55, b=10))
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Ce que les données permettent de dire")
    if len(series) >= 2 and delta is not None:
        direction = "augmenté" if delta > 0 else "diminué" if delta < 0 else "est resté stable"
        st.write(
            f"Sur la période filtrée, **{short_measure} a {direction} de {abs(delta):.1f} %** "
            f"entre {int(series.iloc[0]['Année'])} et {int(series.iloc[-1]['Année'])}. "
            "Interpréter ce résultat selon l'unité, la station ou la méthode de mesure décrite par la source."
        )
    else:
        st.write("Il n'y a pas assez de valeurs non manquantes pour calculer une variation sur la période choisie.")
    st.info(
        "Limite importante : les mesures d'air sont annuelles, alors que les arrêts et lignes décrivent "
        "le réseau. Les données actuelles ne permettent pas d'attribuer la variation de pollution au transport."
    )

# ----------------------------- 02 Air trends -----------------------------
with tabs[1]:
    st.subheader("02 — La pollution évolue-t-elle dans la bonne direction ?")
    st.markdown(
        '<div class="story"><b>Question :</b> observe-t-on une hausse, une baisse ou une stabilité, '
        'et cette lecture dépend-elle du polluant choisi ?</div>',
        unsafe_allow_html=True,
    )
    if series.empty:
        st.warning("Aucune observation exploitable pour la sélection actuelle.")
    else:
        a, b, c = st.columns(3)
        a.metric("Première observation", str(int(series.iloc[0]["Année"])))
        b.metric("Valeur initiale", display_num(series.iloc[0][selected_measure], 3))
        c.metric("Valeur finale", display_num(series.iloc[-1][selected_measure], 3))

        trend_fig = px.line(
            series, x="Année", y=selected_measure, markers=True,
            labels={"Année": "Année", selected_measure: short_measure},
            title=f"Évolution annuelle — {short_measure}",
            template="plotly_white",
        )
        trend_fig.update_traces(
            line=dict(width=3),
            hovertemplate="Année : %{x}<br>Valeur : %{y:.3f}<extra></extra>",
        )
        trend_fig.update_layout(xaxis=dict(dtick=1), yaxis_title=short_measure)
        st.plotly_chart(trend_fig, use_container_width=True)

        changes = []
        for col in measurement_columns:
            valid = air_f[["Année", col]].dropna().sort_values("Année")
            if len(valid) >= 2:
                change = pct_change(valid.iloc[0][col], valid.iloc[-1][col])
                if change is not None:
                    changes.append({
                        "Indicateur": short_label(col),
                        "Année initiale": int(valid.iloc[0]["Année"]),
                        "Année finale": int(valid.iloc[-1]["Année"]),
                        "Valeur initiale": valid.iloc[0][col],
                        "Valeur finale": valid.iloc[-1][col],
                        "Variation (%)": change,
                    })
        if changes:
            change_df = pd.DataFrame(changes).sort_values("Variation (%)")
            st.markdown("#### Quels indicateurs changent le plus ?")
            st.caption("Comparaison des variations relatives entre la première et la dernière valeur disponible de chaque indicateur dans la période filtrée.")
            fig = px.bar(
                change_df, x="Variation (%)", y="Indicateur", orientation="h",
                color="Variation (%)", color_continuous_midpoint=0,
                hover_data=["Année initiale", "Année finale", "Valeur initiale", "Valeur finale"],
                title="Variation relative par indicateur",
                labels={"Variation (%)": "Variation (%)"},
                template="plotly_white",
            )
            fig.add_vline(x=0, line_dash="dash", line_color="gray")
            fig.update_layout(coloraxis_showscale=False, yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Comparer les trajectoires")
        chosen = st.multiselect(
            "Indicateurs à afficher",
            options=measurement_columns,
            default=[selected_measure] + [c for c in measurement_columns if c != selected_measure][:2],
            format_func=short_label,
        )
        if chosen:
            # Index base 100 : compare les trajectoires, pas les unités absolues.
            normalized_rows = []
            for col in chosen:
                valid = air_f[["Année", col]].dropna().sort_values("Année")
                if not valid.empty and valid.iloc[0][col] != 0:
                    for _, row in valid.iterrows():
                        normalized_rows.append({
                            "Année": int(row["Année"]),
                            "Indicateur": short_label(col),
                            "Indice (base 100)": row[col] / valid.iloc[0][col] * 100,
                        })
            if normalized_rows:
                norm = pd.DataFrame(normalized_rows)
                fig = px.line(
                    norm, x="Année", y="Indice (base 100)", color="Indicateur",
                    markers=True, title="Trajectoires normalisées (première valeur = 100)",
                    template="plotly_white",
                )
                fig.add_hline(y=100, line_dash="dot", line_color="gray")
                fig.update_layout(xaxis=dict(dtick=1), yaxis_title="Indice (base 100)")
                st.plotly_chart(fig, use_container_width=True)
                st.caption("L'indice compare l'évolution relative ; il ne rend pas les unités ou les seuils sanitaires équivalents.")
            else:
                st.info("Impossible de normaliser les indicateurs sélectionnés (valeurs de référence absentes ou nulles).")

# ----------------------------- 03 Map and network -----------------------------
with tabs[2]:
    st.subheader("03 — Où se concentre le réseau de transport ?")
    st.markdown(
        '<div class="story"><b>Question :</b> quelle est la distribution géographique des arrêts répertoriés ? '
        'La densité spatiale représente la concentration des points, pas l’intensité de service.</div>',
        unsafe_allow_html=True,
    )
    map_data = stops[["stop_name", "stop_lat", "stop_lon"]].dropna().drop_duplicates().copy()
    max_points = st.select_slider(
        "Nombre maximal de points sur la carte",
        options=[1000, 3000, 5000, 10000, 15000],
        value=5000,
    )
    if len(map_data) > max_points:
        map_data = map_data.sample(n=max_points, random_state=42)
    st.caption(f"{len(map_data):,} arrêts affichés sur {len(stops):,} arrêts géolocalisés.".replace(",", " "))

    if not map_data.empty:
        if map_mode == "Densité spatiale":
            layer = pdk.Layer(
                "HexagonLayer",
                data=map_data,
                get_position="[stop_lon, stop_lat]",
                radius=300,
                elevation_scale=15,
                elevation_range=[0, 1200],
                pickable=True,
                extruded=True,
                coverage=0.8,
            )
            view = pdk.ViewState(
                latitude=float(map_data["stop_lat"].median()),
                longitude=float(map_data["stop_lon"].median()),
                zoom=8,
                pitch=35,
            )
            deck = pdk.Deck(
                layers=[layer],
                initial_view_state=view,
                tooltip={"text": "Concentration relative d'arrêts"},
                map_style=None,
            )
            st.pydeck_chart(deck, use_container_width=True)
        else:
            layer = pdk.Layer(
                "ScatterplotLayer",
                data=map_data,
                get_position="[stop_lon, stop_lat]",
                get_radius=45,
                get_fill_color=[8, 127, 140, 150],
                pickable=True,
                auto_highlight=True,
            )
            view = pdk.ViewState(
                latitude=float(map_data["stop_lat"].median()),
                longitude=float(map_data["stop_lon"].median()),
                zoom=8,
                pitch=0,
            )
            deck = pdk.Deck(
                layers=[layer],
                initial_view_state=view,
                tooltip={"text": "Arrêt : {stop_name}"},
                map_style=None,
            )
            st.pydeck_chart(deck, use_container_width=True)
        st.caption("L'affichage peut utiliser un échantillon aléatoire reproductible si le nombre d'arrêts dépasse la limite choisie.")
    else:
        st.warning("Aucun arrêt avec des coordonnées valides.")

    left, right = st.columns(2)
    with left:
        st.markdown("#### Noms d'arrêts les plus fréquents dans le fichier")
        stop_names = stops["stop_name"].value_counts().head(15).rename_axis("Nom de l'arrêt").reset_index(name="Occurrences")
        fig = px.bar(
            stop_names.sort_values("Occurrences"), x="Occurrences", y="Nom de l'arrêt",
            orientation="h", title="Top 15 des noms d'arrêts répétés",
            template="plotly_white",
        )
        fig.update_layout(yaxis_title="", margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Un même nom peut désigner plusieurs arrêts distincts ; ce classement ne mesure pas la fréquentation.")
    with right:
        st.markdown("#### Répartition des lignes par type")
        if not routes_f.empty:
            counts = routes_f.groupby("type_transport").size().reset_index(name="Lignes")
            fig = px.pie(counts, names="type_transport", values="Lignes", hole=.48, title="Part des enregistrements par type")
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Aucune ligne pour les types sélectionnés.")

# ----------------------------- 04 Comparisons -----------------------------
with tabs[3]:
    st.subheader("04 — Comparer sans confondre les indicateurs")
    st.markdown(
        '<div class="story"><b>Question :</b> quelles différences ressortent des données et quelles comparaisons '
        'sont réellement justifiées par leur granularité ?</div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        st.markdown("#### Distribution de l'indicateur sélectionné")
        vals = air_f[["Année", selected_measure]].dropna()
        if len(vals):
            fig = px.histogram(
                vals, x=selected_measure, nbins=min(8, max(3, len(vals))),
                marginal="box", title=short_measure,
                labels={selected_measure: short_measure}, template="plotly_white",
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Avec peu d'années, l'histogramme reste descriptif et ne doit pas être interprété comme une distribution de long terme.")
        else:
            st.info("Pas de valeurs à distribuer.")
    with right:
        st.markdown("#### Variabilité annuelle")
        if len(vals) >= 2:
            desc = vals[selected_measure].describe()
            st.metric("Écart-type sur la période", display_num(desc["std"], 3))
            st.metric("Étendue min–max", f"{display_num(desc['min'], 3)} – {display_num(desc['max'], 3)}")
            fig = px.box(
                vals, y=selected_measure, points="all",
                title=f"Dispersion de {short_measure}",
                labels={selected_measure: short_measure}, template="plotly_white",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Au moins deux observations sont nécessaires.")
    st.markdown("#### Tableau analytique de la période filtrée")
    if not air_f.empty:
        summary_rows = []
        for col in measurement_columns:
            v = air_f[["Année", col]].dropna().sort_values("Année")
            if not v.empty:
                summary_rows.append({
                    "Indicateur": short_label(col),
                    "Observations": len(v),
                    "Première année": int(v.iloc[0]["Année"]),
                    "Dernière année": int(v.iloc[-1]["Année"]),
                    "Minimum": v[col].min(),
                    "Moyenne": v[col].mean(),
                    "Maximum": v[col].max(),
                    "Variation (%)": pct_change(v.iloc[0][col], v.iloc[-1][col]) if len(v) >= 2 else None,
                })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    st.warning(
        "Le fichier de pollution comporte des mesures annuelles agrégées. "
        "Ne pas calculer de corrélation avec le nombre d'arrêts ou de lignes : ces variables ne sont pas alignées par année, zone et observation."
    )

# ----------------------------- 05 Data quality -----------------------------
with tabs[4]:
    st.subheader("05 — La qualité des données conditionne la qualité des conclusions")
    st.markdown(
        '<div class="story"><b>Question :</b> quelles anomalies pourraient fragiliser l’analyse, et quelles règles de nettoyage ont été appliquées ?</div>',
        unsafe_allow_html=True,
    )
    quality_tables = {
        "Arrêts GTFS nettoyés": stops,
        "Lignes GTFS": routes,
        "Qualité de l'air": air,
    }
    quality_rows = []
    for name, frame in quality_tables.items():
        total_cells = frame.shape[0] * frame.shape[1]
        missing_cells = int(frame.isna().sum().sum())
        quality_rows.append({
            "Jeu de données": name,
            "Lignes": len(frame),
            "Colonnes": frame.shape[1],
            "Doublons de lignes": int(frame.duplicated().sum()),
            "Cellules manquantes": missing_cells,
            "Taux de cellules manquantes (%)": round(100 * missing_cells / total_cells, 2) if total_cells else 0,
        })
    quality_df = pd.DataFrame(quality_rows)
    st.dataframe(quality_df, use_container_width=True, hide_index=True)

    selected_quality = st.selectbox("Examiner les valeurs manquantes", list(quality_tables.keys()))
    frame = quality_tables[selected_quality]
    missing = pd.DataFrame({
        "Colonne": frame.columns,
        "Valeurs manquantes": [int(frame[c].isna().sum()) for c in frame.columns],
    })
    missing["Taux manquant (%)"] = (missing["Valeurs manquantes"] / max(len(frame), 1) * 100).round(2)
    missing = missing.sort_values("Taux manquant (%)", ascending=False)
    nonzero_missing = missing[missing["Valeurs manquantes"] > 0]
    if nonzero_missing.empty:
        st.success("Aucune valeur manquante détectée dans ce tableau.")
    else:
        fig = px.bar(
            nonzero_missing.head(25).sort_values("Taux manquant (%)"),
            x="Taux manquant (%)", y="Colonne", orientation="h",
            title="Colonnes avec le plus de valeurs manquantes",
            labels={"Taux manquant (%)": "Cellules manquantes (%)"},
            template="plotly_white",
        )
        st.plotly_chart(fig, use_container_width=True)
    st.dataframe(missing, use_container_width=True, hide_index=True)

    # Validation checks and their denominators are explicit.
    lat_ok = stops["stop_lat"].between(48.0, 49.3).all() if not stops.empty else False
    lon_ok = stops["stop_lon"].between(1.4, 3.6).all() if not stops.empty else False
    years_ok = air["Année"].between(1900, 2100).all() if not air.empty else False
    unique_ids = stops["stop_id"].is_unique if "stop_id" in stops.columns and not stops.empty else False
    checks = pd.DataFrame([
        {"Contrôle": "Coordonnées dans l'emprise géographique retenue", "Résultat": "OK" if lat_ok and lon_ok else "À vérifier", "Portée": "Arrêts conservés après filtrage"},
        {"Contrôle": "Années plausibles (1900–2100)", "Résultat": "OK" if years_ok else "À vérifier", "Portée": "CSV qualité de l'air"},
        {"Contrôle": "Identifiants d'arrêts uniques", "Résultat": "OK" if unique_ids else "À vérifier / indisponible", "Portée": "Arrêts GTFS conservés"},
    ])
    st.markdown("#### Contrôles de validation")
    st.dataframe(checks, use_container_width=True, hide_index=True)
    st.caption(
        "Attention : les arrêts affichés sont déjà filtrés sur une emprise géographique approximative de l'Île-de-France. "
        "Le contrôle des coordonnées ne valide donc pas les lignes éliminées avant affichage."
    )

# ----------------------------- 06 Conclusions -----------------------------
with tabs[5]:
    st.subheader("06 — Des observations aux décisions")
    st.markdown(
        '<div class="story"><b>Conclusion provisoire :</b> le dashboard permet d’explorer séparément '
        'la structure du réseau et l’évolution annuelle de la qualité de l’air. Une décision solide exige '
        'des données mieux alignées.</div>',
        unsafe_allow_html=True,
    )
    if len(series) >= 2 and delta is not None:
        if delta < 0:
            st.markdown(f"**Constat 1 —** {short_measure} diminue de {abs(delta):.1f} % entre {int(series.iloc[0]['Année'])} et {int(series.iloc[-1]['Année'])} dans la sélection actuelle.")
        elif delta > 0:
            st.markdown(f"**Constat 1 —** {short_measure} augmente de {delta:.1f} % entre {int(series.iloc[0]['Année'])} et {int(series.iloc[-1]['Année'])} dans la sélection actuelle.")
        else:
            st.markdown(f"**Constat 1 —** {short_measure} reste stable entre les deux observations extrêmes de la sélection.")
    else:
        st.markdown("**Constat 1 —** pas assez d'observations pour calculer une variation sur la période.")
    st.markdown(
        f"**Constat 2 —** le réseau chargé comprend **{len(stops):,} arrêts géolocalisés** et "
        f"**{len(routes_f):,} enregistrements de lignes** pour les modes choisis.".replace(",", " ")
    )
    st.markdown(
        "**Constat 3 —** la qualité des données doit être examinée avant toute interprétation : "
        "les valeurs manquantes, doublons et règles de filtrage influencent les résultats."
    )
    st.markdown("#### Pour aller plus loin : données nécessaires")
    st.write(
        "- Mesures de pollution par station et par date (idéalement horaires ou journalières)."
    )
    st.write("- Données de fréquentation, de trafic ou d'offre de transport par zone et période.")
    st.write("- Variables de contexte : météo, saison, travaux, restrictions de circulation et évolution démographique.")
    st.write("- Documentation des unités, méthodes de mesure, couverture et incertitude.")
    st.warning(
        "Les résultats actuels sont descriptifs. Ils ne démontrent pas que le réseau de transport cause une hausse "
        "ou une baisse de pollution. Une étude causale nécessiterait un protocole, des variables de contrôle et une granularité compatible."
    )
    st.markdown("#### Exporter les données résumées")
    if not air_f.empty:
        st.download_button(
            "Télécharger les mesures filtrées (CSV)",
            data=air_f.to_csv(index=False).encode("utf-8-sig"),
            file_name="urbanpulse_air_filtre.csv",
            mime="text/csv",
        )
    st.download_button(
        "Télécharger le bilan qualité des données (CSV)",
        data=quality_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="urbanpulse_qualite_donnees.csv",
        mime="text/csv",
    )

# ----------------------------- Footer / sources -----------------------------
st.divider()
with st.expander("Sources, méthode et limites"):
    st.markdown(
        """
        **Réseau de transport**  
        [Île-de-France Mobilités — Réseau urbain et interurbain sur data.gouv.fr](https://www.data.gouv.fr/datasets/reseau-urbain-et-interurbain-dile-de-france-mobilites)

        **Qualité de l'air**  
        [Paris Data / Airparif — Concentrations annuelles de NO₂, PM2.5, PM10 et O₃ à partir de 2015](https://opendata.paris.fr/explore/dataset/qualite-de-lair-concentration-moyenne-no2-pm25-pm10-o3-a-partir-de-2015/)

        **Préparation et limites**
        - Les données sont chargées depuis `data/` et mises en cache avec `st.cache_data`.
        - Les coordonnées manquantes ou hors de l'emprise retenue sont exclues de la carte.
        - Le fichier `stop_times.txt` n'est pas chargé, car il peut être très volumineux.
        - Les intitulés de colonnes sources sont conservés dans les calculs ; les libellés courts servent uniquement à la présentation.
        - Les unités doivent être confirmées dans les métadonnées officielles avant toute comparaison réglementaire.
        - La concentration d'arrêts sur la carte n'est ni la fréquentation, ni la capacité, ni la qualité du service.
        - Les deux sources n'ont pas la même granularité géographique et temporelle : aucune relation causale n'est inférée.
        """
    )
st.caption("UrbanPulse · Projet de data storytelling · Analyse descriptive et limites documentées")
