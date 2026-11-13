# Agent finance et marchés – Projet 6

Objectif : repérer à l'avance qu'un fournisseur va coûter plus cher, livrer en retard ou ne plus livrer du tout.

## Les cinq familles de signaux

| Famille | Sources | Accès |
| --- | --- | --- |
| 1. Marchés | Brent, cuivre, aluminium (yfinance) ; gaz Europe, zinc, nickel (Banque mondiale) ; gazole UE (Weekly Oil Bulletin) ; GSCPI ; EUR/USD, EUR/CNY (BCE) ; prix de production UE (Eurostat) | Automatique |
| 1. Marchés | Carbone EU ETS (ICAP), électricité Allemagne (Ember) | Fichier CSV placé dans `data/manuel/` (colonnes date, valeur) |
| 2. Fournisseurs cotés | Cours de bourse (yfinance) | Automatique |
| 3. Santé des fournisseurs | Procédures collectives (BODACC, entreprises françaises) | Automatique |
| 4. Règles et taxes | Federal Register (Entity List, droits de douane US) ; règles UE (tableau `REGLES_UE`, sourcé) | Automatique / suivi manuel |
| 5. Sanctions et propriété | Sanctions UE, Consolidated Screening List (US), maisons mères (GLEIF) | Automatique |

Les fournisseurs du cas d'étude sont décrits dans le tableau `FOURNISSEURS` de `finance_collecte.py` (nom légal, ticker s'il est coté, SIREN s'il est français).

## Contenu

| Fichier | Rôle |
| --- | --- |
| `finance_collecte.py` | Collecte avec cache ; tools `contexte_finance(date, pays, fournisseurs)` et `fiche_fournisseur(cle, date)` au format JSON commun |
| `finance_signaux.ipynb` | Les cinq familles, seuils, validation sur quatre crises de fournisseurs, bruit, délai Brent → gazole, fiche de chaque fournisseur, exports |
| `presentation_finance.ipynb` | Présentation des résultats en sept étapes, fil rouge Nexperia ; lit les fichiers de `sorties/` |
| `sorties/` | Résultats exportés par `finance_signaux.ipynb` |

## Exécution

```bash
pip install -r requirements.txt
python finance_collecte.py verifier          # état de chaque source : ✓ ok, ⚠ historique court, – fichier manuel absent, ✗ erreur
jupyter lab                                  # finance_signaux.ipynb, puis presentation_finance.ipynb
python finance_collecte.py contexte --date 2024-12-10 --pays NL --fournisseurs nexperia
jupyter nbconvert --to html --no-input presentation_finance.ipynb   # présentation sans le code
```

## Limites connues

- Wolfspeed : les anciennes actions ont été annulées à la sortie de faillite (29/09/2025) et Yahoo n'a plus l'historique d'avant. La validation s'appuie sur la baisse publiée dans la presse ; un historique complet placé dans `data/manuel/bourse_wolfspeed.csv` est utilisé en priorité.
- Les prix mensuels (gaz, zinc, nickel, prix de production) sont publiés quelques jours après la fin du mois : l'avance réelle est un peu plus courte que l'avance affichée.
- Les règles UE sont suivies à la main ; seules les règles américaines sont collectées automatiquement.
- Quatre crises de fournisseurs montrent que la méthode peut fonctionner, pas qu'elle est fiable en toutes circonstances.
