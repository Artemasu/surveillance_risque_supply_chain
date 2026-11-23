"""Calculs des volets Météo et Finance : indicateurs, seuils calibrés, rangs, épisodes.

Les deux notebooks appliquent la même méthode (seuil = quantile sur 2010-2020, rang = position dans la période
de calibration, épisodes = jours d'alerte regroupés). Elle est écrite une seule fois, dans `thresholds.py`.
"""
