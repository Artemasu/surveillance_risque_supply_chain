# Ajouter la couche climatique aux notebooks existants

La couche climatique attribue à chaque site sa **classe de Köppen-Geiger** (climat tropical, tempéré, continental…). Elle sert à expliquer les seuils (« un site tempéré océanique a des seuils de pluie bas ») et à les contrôler (deux sites du même climat doivent avoir des seuils proches).

## 0. Préparation (une seule fois)

1. **Installer rasterio** dans ton environnement virtuel :
   ```bash
   pip install rasterio
   ```
2. **Télécharger les cartes** : archive `koppen_geiger_tif.zip` (90 Mo) sur [figshare – Beck et al. 2023](https://figshare.com/articles/dataset/High-resolution_1_km_K_ppen-Geiger_maps_for_1901_2099_based_on_constrained_CMIP6_projections/21789074), puis la décompresser dans le dossier du projet.
3. **Repérer deux fichiers** dans l'archive décompressée :
   - la carte de la période **1991-2020** (un fichier `.tif`) ;
   - le fichier `legend.txt`.

   Je n'ai pas pu ouvrir l'archive : vérifie les noms exacts et adapte les chemins ci-dessous.
4. **Placer `meteo_collecte.py`** dans le même dossier que les notebooks : ils réutilisent sa fonction `classe_climatique`.

Pour vérifier que tout est en place :
```bash
python meteo_collecte.py verifier --lieu "Paris, France" --koppen-tif CHEMIN/VERS/carte.tif --koppen-legende CHEMIN/VERS/legend.txt
```
La ligne « Classe climatique Köppen » doit afficher ✓ et une classe (par exemple `Cfb – ...` pour Paris).

---

## 1. `meteo_supply_chain_v2.ipynb`

### 1.1 Nouvelle cellule, juste après la cellule `SITES = pd.DataFrame(...)` (section 2)

Ajoute d'abord une cellule Markdown :

```markdown
### Le climat de chaque site

On attribue à chaque site sa classe climatique de Köppen-Geiger (cartes à 1 km de Beck et al., 2023, période 1991-2020). La première lettre donne le grand type : A tropical, B aride, C tempéré, D continental, E polaire.
```

Puis la cellule de code :

```python
from meteo_collecte import classe_climatique

KOPPEN_TIF = "koppen_geiger_tif/1991_2020/koppen_geiger_0p01.tif"  # à adapter
KOPPEN_LEGENDE = "koppen_geiger_tif/legend.txt"                   # à adapter

climats = [classe_climatique(s.lat, s.lon, KOPPEN_TIF, KOPPEN_LEGENDE) for s in SITES.itertuples()]
if all(c is None for c in climats):
    print("⚠ Carte Köppen introuvable : vérifier KOPPEN_TIF. Le reste du notebook fonctionne sans.")
SITES["climat"] = [c["classe"] if c else None for c in climats]
SITES["climat_libelle"] = [c["libelle"] if c else None for c in climats]
SITES[["site", "pays", "climat", "climat_libelle"]]
```

### 1.2 Section 4 : ajouter le climat au profil des sites

Dans la cellule `profil = ...`, remplace la **dernière ligne** :

```python
profil.loc[SITES["site"]]
```

par :

```python
profil.join(SITES.set_index("site")["climat"]).loc[SITES["site"]]
```

### 1.3 Section 5 : nouvelle cellule de contrôle, juste après la cellule `SEUILS = ...`

Cellule Markdown :

```markdown
**Contrôle par climat** : des sites du même climat devraient avoir des seuils proches. Un écart important signale soit un effet local réel (relief, côte), soit une erreur de données.
```

Cellule de code :

```python
controle = (SEUILS[SEUILS["indicateur"] == "pluie_3j"]
            .merge(SITES[["site", "climat"]], on="site")
            .dropna(subset=["seuil"]))
if controle["climat"].notna().any():
    display(controle.groupby("climat")["seuil"]
            .agg(sites="count", minimum="min", mediane="median", maximum="max").round(0))
    display(controle.sort_values(["climat", "seuil"])[["climat", "site", "seuil"]].round(0))
else:
    print("Pas de classe climatique : voir la cellule « Le climat de chaque site ».")
```

### 1.4 Export : rien à changer

La cellule d'export enregistre déjà `SITES` dans `sorties/meteo_sites.csv` : les colonnes `climat` et `climat_libelle` y seront automatiquement.

---

## 2. `presentation_meteo.ipynb`

### 2.1 Cellule de préparation : charger les sites

Dans le dictionnaire `fichiers`, ajoute la ligne :

```python
    "sites": "meteo_sites.csv",
```

Puis, après la ligne `previsions = pd.read_csv(...)`, ajoute :

```python
sites = pd.read_csv(SORTIES / fichiers["sites"])
if "climat" not in sites.columns:
    sites["climat"] = None
```

### 2.2 Section 2 : afficher le climat à côté de chaque site

Dans la cellule du graphique des seuils, remplace :

```python
pluie = seuils[seuils["indicateur"] == "pluie_3j"].dropna().sort_values("seuil")
bas, haut = pluie.iloc[0], pluie.iloc[-1]

fig, ax = plt.subplots(figsize=(9, 4.2))
ax.barh(pluie["site"], pluie["seuil"], color=BLEU, height=0.6, zorder=2)
```

par :

```python
pluie = (seuils[seuils["indicateur"] == "pluie_3j"].dropna()
         .merge(sites[["site", "climat"]], on="site", how="left").sort_values("seuil"))
pluie["etiquette"] = pluie["site"] + np.where(pluie["climat"].notna(), " · " + pluie["climat"].astype(str), "")
bas, haut = pluie.iloc[0], pluie.iloc[-1]

fig, ax = plt.subplots(figsize=(9, 4.2))
ax.barh(pluie["etiquette"], pluie["seuil"], color=BLEU, height=0.6, zorder=2)
```

Et à la fin de la même cellule, après le `dire(...)` existant, ajoute :

```python
if pd.notna(bas.climat) and pd.notna(haut.climat):
    dire(f"Le climat l'explique : {bas.site} a un climat **{bas.climat}**, {haut.site} un climat **{haut.climat}**. "
         "Dans le code de Köppen, la première lettre donne le grand type : A tropical, B aride, "
         "C tempéré, D continental, E polaire.")
```

---

## 3. Pour aller plus loin (facultatif)

`meteo_collecte.py` contient aussi l'outil `contexte_meteo(lieu, date_cible)` de l'agent météo : il renvoie le JSON commun des agents, avec chaque valeur située par rapport aux **normales 1991-2020** du lieu (les normales officielles de l'Organisation météorologique mondiale). À terme, le notebook v2 pourra importer ses fonctions de collecte (`historique`, `debit`, `trouver_fleuve`) au lieu de les redéfinir : il n'y aura alors qu'un seul code de collecte à maintenir.