# Agent météo : interroger la base en langage naturel

## Principe

```
notebook (sorties/*.csv)  ->  base SQLite (base_meteo.py)  ->  outils  ->  LLM  ->  réponse + sources
```

Outils : `lister_alertes` (alertes passées et prévues), `profil_site` (fiche, seuils, fréquence), `executer_sql` (toute question chiffrée), `decrire_base`.

Le LLM ne lit jamais les données directement et n'a pas accès à Internet. Il choisit un **outil**, le code
Python l'exécute sur la base interne **en lecture seule**, puis le LLM rédige la réponse à partir du résultat.
Chaque réponse indique les requêtes utilisées (`source_id`) : on peut toujours vérifier d'où vient un chiffre.

## Fichiers

| Fichier | Rôle | Quand le modifier |
|---|---|---|
| `base_meteo.py` | construit `data/meteo.db` à partir du dossier `sorties/` (résultats du notebook) ; décrit les tables (`SCHEMA`) | nouvelle colonne ou table |
| `llm/config.py` | choix du fournisseur et du modèle | nouveau fournisseur |
| `llm/fournisseurs.py` | dialogue avec les API (format OpenAI et format Anthropic) | rarement |
| `llm/outils.py` | les outils appelables par le LLM | nouvel outil |
| `llm/prompts/agent_meteo.md` | la consigne de l'agent | ajuster le comportement |
| `llm/agent.py` | la boucle question -> outils -> réponse ; création des agents | nouvel agent (médias, finance) |
| `assistant_meteo.py` | ligne de commande | - |
| `mise_a_jour.py` | mise à jour quotidienne de la base (et planification à 18 h) | - |
| `.env` | fournisseur, modèle, clés (copie de `env_exemple.txt`, **jamais sur GitHub**) | - |

## Mise en route

```powershell
# toutes les commandes se lancent depuis le dossier meteo
python base_meteo.py                                         # 1. base SQLite (à relancer après chaque exécution du notebook)
copy env_exemple.txt .env                                     # 2. configuration (puis compléter .env)
python assistant_meteo.py tester                             # 3. vérification
python assistant_meteo.py demander "Quelles alertes à Spruce Pine pendant l'ouragan Helene fin septembre 2024 ?"
python assistant_meteo.py discuter                           # conversation
```

Options : `--journal` (affiche les outils appelés), `--json` (format commun des agents),
`--fournisseur mistral` / `--modele ...` (changer de LLM sans toucher au .env).

## Mise à jour quotidienne

```powershell
python mise_a_jour.py                      # mise à jour immédiate
python mise_a_jour.py --planifier 18:00    # automatique chaque jour à 18 h (tâche Windows)
python mise_a_jour.py --deplanifier        # arrêter l'automatisation
```

Chaque mise à jour ajoute les jours manquants (ERA5 jusqu'à J-6, prévision pour les jours récents,
marqués « provisoire » et remplacés ensuite), recalcule indicateurs, score et alertes avec les seuils du
notebook, et renouvelle les alertes prévues à 16 jours. Suivi dans `data/mise_a_jour.log`.
Après une reconstruction (`python base_meteo.py`), relancer `python mise_a_jour.py` pour rattraper.

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

**Ajouter une colonne** : l'ajouter dans le notebook (fichiers de sorties/), puis sa description dans `SCHEMA` (`base_meteo.py`).
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
