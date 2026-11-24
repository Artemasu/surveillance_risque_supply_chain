# Agent météo : interroger la base en langage naturel

## Principe

```
collecte (meteo_collecte.py)  ->  base SQLite (base_meteo.py)  ->  outils  ->  LLM  ->  réponse + sources
```

Le LLM ne lit jamais les données directement et n'a pas accès à Internet. Il choisit un **outil**, le code
Python l'exécute sur la base interne **en lecture seule**, puis le LLM rédige la réponse à partir du résultat.
Chaque réponse indique les requêtes utilisées (`source_id`) : on peut toujours vérifier d'où vient un chiffre.

## Fichiers

| Fichier | Rôle | Quand le modifier |
|---|---|---|
| `base_meteo.py` | construit `data/meteo.db` à partir de la collecte ; décrit les tables (`SCHEMA`) | nouvelle colonne ou table |
| `llm/config.py` | choix du fournisseur et du modèle | nouveau fournisseur |
| `llm/fournisseurs.py` | dialogue avec les API (format OpenAI et format Anthropic) | rarement |
| `llm/outils.py` | les outils appelables par le LLM | nouvel outil |
| `llm/prompts/agent_meteo.md` | la consigne de l'agent | ajuster le comportement |
| `llm/agent.py` | la boucle question -> outils -> réponse ; création des agents | nouvel agent (médias, finance) |
| `assistant_meteo.py` | ligne de commande | - |
| `.env` | fournisseur, modèle, clés (copie de `.env.exemple`, **jamais sur GitHub**) | - |

## Mise en route

```powershell
python meteo_collecte.py collecter --sites mes_sites.csv    # 1. collecte (si pas déjà faite)
python base_meteo.py                                         # 2. base SQLite
copy .env.exemple .env                                       # 3. configuration (puis compléter .env)
python assistant_meteo.py tester                             # 4. vérification
python assistant_meteo.py demander "Quels sites ont eu des pluies exceptionnelles en 2024 ?"
python assistant_meteo.py discuter                           # conversation
```

Options : `--journal` (affiche les outils appelés), `--json` (format commun des agents),
`--fournisseur mistral` / `--modele ...` (changer de LLM sans toucher au .env).

## Choisir le LLM

| Fournisseur | Coût | Avantages | Inconvénients |
|---|---|---|---|
| `ollama` (défaut, `qwen3:8b`) | gratuit | local : aucune donnée ne sort de l'ordinateur | lent sur processeur ; 5 Go à télécharger |
| `mistral` | payant à l'usage (offre gratuite limitée) | entreprise européenne, rapide | clé API |
| `anthropic` (Claude) | payant à l'usage | très bon en SQL et en raisonnement | clé API |

Ollama : installer depuis ollama.com, puis `ollama pull qwen3:8b` (ou `qwen3:4b`, plus léger).
Le modèle doit savoir appeler des outils (« tools ») : c'est le cas de Qwen3, Llama 3.1+, Mistral.

## Faire évoluer

**Ajouter un outil** (dans `llm/outils.py`), puis l'ajouter à la liste d'outils dans `creer_agent_meteo` :

```python
@outil("cumul_pluie_mois", "Cumul de pluie mensuel d'un site.",
       {"site": {"type": "string", "description": "nom du site"}}, obligatoires=["site"])
def cumul_pluie_mois(site):
    return _lire("SELECT strftime('%Y-%m', date) AS mois, SUM(pluie_mm) AS pluie_mm "
                 "FROM meteo_jour WHERE site = ? GROUP BY mois ORDER BY mois", (site,))
```

**Ajouter une colonne** : l'ajouter dans la collecte, puis sa description dans `SCHEMA` (`base_meteo.py`).
Le LLM la découvre automatiquement.

**Créer l'agent médias ou finance** : un prompt `llm/prompts/agent_medias.md`, ses outils, et une fonction
`creer_agent_medias()` sur le modèle de `creer_agent_meteo()`. Tous les agents renvoient le même format JSON
(`agent`, `question`, `reponse`, `sources`, `donnees_manquantes`), ce qui permettra à un agent final de
les combiner et de les relier au graphe.

## Sécurité

- connexion à la base en lecture seule, une seule requête SELECT à la fois, arrêt après 5 s ;
- 100 lignes au plus renvoyées au LLM ;
- les clés sont lues dans `.env` et jamais affichées.

À ajouter dans `.gitignore` : `.env`, `data/meteo.db`.
