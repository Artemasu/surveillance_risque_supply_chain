"""Connecteurs : accès brut aux sources externes (météo, marchés, registres), avec cache disque.

Repris des modules `meteo_collecte.py` et `finance_collecte.py` (volets Météo et Finance du projet) :
mêmes sources, mêmes règles, mais sans effet de bord à l'import, avec des chemins réglés par `settings`
et un cache unique dont la durée de vie dépend de la source (une prévision ne reste jamais en cache des mois).
Aucune logique métier ici : seuils, rangs et épisodes sont dans `src/analytics`.
"""
