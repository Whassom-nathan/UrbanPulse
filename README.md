# UrbanPulse — Mobilité et qualité de l’air

## Question de départ

**L’évolution de la qualité de l’air et la structure du réseau de transport permettent-elles d’identifier des tendances utiles pour la planification urbaine ?**

UrbanPulse est une application Streamlit de data storytelling. Elle explore deux sources publiques : le réseau GTFS d’Île-de-France Mobilités et des mesures annuelles de qualité de l’air publiées par Paris Data / Airparif.

## Parcours narratif

1. **Diagnostic** — KPI et première lecture des données.
2. **Tendances de l’air** — évolution annuelle, variations relatives et trajectoires normalisées.
3. **Géographie du réseau** — carte des arrêts, vue de densité et distribution des lignes.
4. **Comparaisons** — distributions et statistiques descriptives.
5. **Qualité des données** — valeurs manquantes, doublons et contrôles de cohérence.
6. **Conclusions** — constats, limites et données supplémentaires nécessaires.

## Sources

- Transport : https://www.data.gouv.fr/datasets/reseau-urbain-et-interurbain-dile-de-france-mobilites
- Qualité de l’air : https://opendata.paris.fr/explore/dataset/qualite-de-lair-concentration-moyenne-no2-pm25-pm10-o3-a-partir-de-2015/

Vérifier les métadonnées officielles pour les unités, la méthode de mesure, la couverture, la licence et la date de mise à jour.

## Installation

Prérequis : Python 3.12 recommandé.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

## Organisation attendue

```text
StreamlitDashboard/
├── app.py
├── requirements.txt
├── README.md
└── data/
    ├── air_quality.csv
    └── transport_gtfs.zip
```

## Méthode et limites

- `st.cache_data` est utilisé pour mettre en cache le chargement.
- Les arrêts sans coordonnées valides ou hors de l’emprise géographique retenue sont écartés de la carte.
- Le très volumineux `stop_times.txt` n’est pas chargé.
- Le nombre d’arrêts ou de lignes répertoriés ne mesure pas la fréquentation ni la capacité réelle.
- Les mesures de pollution sont annuelles, tandis que le réseau GTFS décrit la structure du réseau. Les sources ne sont pas alignées par zone et période ; aucune causalité entre transport et pollution ne peut être déduite.
- Les unités doivent être vérifiées dans les métadonnées officielles avant toute interprétation réglementaire.

## Reproductibilité

Les dépendances principales sont épinglées dans `requirements.txt`. L’application doit être testée dans un environnement propre avant le dépôt final.
