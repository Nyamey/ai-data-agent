# ai-data-agent

**Agent IA open source pour l'analyse de données, conçu pour raisonner comme un analyste, pas seulement générer du SQL.**

`ai-data-agent` transforme une question métier en une analyse structurée, vérifiée et actionnable. Au lieu de produire une réponse en une seule passe, l'**agent** (exécuté en ligne de commande) suit un workflow d'analyste : il cadre le problème, inspecte les données, **s'arrête dans le terminal pour demander une validation humaine**, construit l'analyse, la teste, la valide, puis formule des recommandations classées par impact et faisabilité.

Le projet est construit avec **LangGraph** (orchestration multi-étapes avec état persistant), **DuckDB** (moteur analytique en mémoire), **Streamlit** (interface web) et un **serveur MCP** qui expose la base à n'importe quel assistant IA compatible (Claude Desktop, VS Code…).

> **Deux interfaces distinctes.** L'**agent LangGraph en 7 étapes** (avec point de contrôle humain) s'exécute en CLI via `python -m agent.main`. L'**application Streamlit** (`app.py`) est une interface plus simple, indépendante : elle effectue une analyse LLM en une seule passe, sans le workflow d'agent ni l'étape d'approbation. Unifier les deux fait partie de la [roadmap](#roadmap).

---

## Pourquoi ce projet

La plupart des outils « text-to-SQL » sautent directement à la requête et produisent des réponses plausibles mais non vérifiées. `ai-data-agent` reproduit la démarche d'un analyste senior :

- **Cadrer avant de calculer** : définir la métrique de façon opérationnelle et reformuler la question de manière testable évite de partir dans la mauvaise direction.
- **Human-in-the-loop** : en mode CLI, l'agent marque une pause dans le terminal après l'inspection des données et attend une approbation explicite avant de lancer l'analyse.
- **Traçabilité** : chaque étape est journalisée dans un *audit trail*, et l'état complet est persisté (SQLite) pour être repris ou audité.
- **Livrables prêts à l'emploi** : export Markdown, CSV, Excel et PowerPoint depuis l'interface Streamlit (les générateurs Excel/PPTX de l'agent CLI existent mais ne sont pas encore branchés sur sa sortie — voir [roadmap](#roadmap)).

---

## Fonctionnalités

- **Workflow d'agent en 7 étapes** orchestré par LangGraph avec état typé (Pydantic) et checkpointing SQLite.
- **Point de contrôle humain** (human-in-the-loop) après l'inspection des données, en mode ligne de commande (invite `input()` dans le terminal).
- **Inspection automatique des données** : schéma, volumétrie, plage de dates, valeurs manquantes, doublons, besoin d'agrégation.
- **Analyse des facteurs explicatifs** : comparaison de la métrique selon plusieurs dimensions (plateforme, version, segment, région…).
- **Étape de validation** : rapprochement des comptes, vérification de reproductibilité et de cohérence des résultats.
- **Recommandations classées** par impact, faisabilité et délai.
- **Pipeline de streaming** : surveillance d'un dossier (watchdog) qui déclenche une analyse automatique à l'arrivée de tout nouveau fichier. Un détecteur d'anomalies par z-score (`AnomalyDetector`) est disponible mais pas encore branché sur cette décision de déclenchement (toute arrivée de fichier lance une analyse, indépendamment d'une anomalie détectée).
- **Serveur MCP DuckDB** : expose la base analytique aux assistants IA compatibles MCP.
- **Interface Streamlit** (autonome) : upload jusqu'à 5 fichiers CSV, nettoyage automatique (encodage, séparateur, décimales FR, dates, doublons), historique des analyses en session, analyse LLM en une passe et export Markdown / CSV / Excel / PowerPoint. Note : cette interface n'invoque pas encore l'agent en 7 étapes.
- **Multi-provider LLM avec fallback** : Groq, Gemini, OpenRouter, Mistral via LiteLLM. L'agent CLI bascule automatiquement vers OpenRouter (modèle gratuit) si le provider principal échoue — Gemini n'est plus utilisé comme filet de secours car son accès via l'API Generative Language nécessite désormais une facturation activée sur de nombreux comptes. Dans l'app Streamlit, le choix Groq/OpenRouter est manuel (menu déroulant), et l'option OpenRouter essaie automatiquement plusieurs modèles gratuits en cascade si l'un est rate-limité.
- **Sécurité** : neutralisation des injections de formule CSV/Excel (CWE-1236) sur les exports, lecture CSV robuste (encodage et séparateur devinés, utile pour les exports Excel FR).

---

## Architecture

Le cœur du système est un graphe LangGraph. Après l'inspection, une arête conditionnelle renvoie vers un point de contrôle humain ; l'analyse ne se poursuit qu'après approbation.

```text
Cadrage → Inspection → [Approbation humaine] → Construction → Test → Validation → Recommandations
                            │ (rejet)
                            └────────────► Fin
```

| Étape | Nœud | Rôle |
| --- | --- | --- |
| 1. Cadrage | `framing` | Définit la métrique, reformule la question, fixe la période de comparaison et les hypothèses |
| 2. Inspection | `inspection` | Charge les données dans DuckDB et en extrait les métadonnées |
| 3. Approbation | `approval` | Point de contrôle humain — attend une validation explicite |
| 4. Construction | `build` | Calcule la métrique (ex. rétention hebdomadaire, cohortes) via DuckDB |
| 5. Test | `test` | Compare la métrique selon les dimensions catégorielles |
| 6. Validation | `validate` | Rapproche les comptes et vérifie la cohérence |
| 7. Recommandations | `recommend` | Formule des recommandations actionnables classées |

Un schéma détaillé est disponible dans [`docs/architecture.svg`](docs/architecture.svg).

### Stack technique

| Domaine | Technologie |
| --- | --- |
| Orchestration d'agent | LangGraph 1.1 + LangChain Core |
| Persistance de l'état | SQLite (checkpointer LangGraph) |
| Moteur analytique | DuckDB |
| Accès LLM | LiteLLM (Groq, Gemini, OpenRouter, Mistral) |
| Interface web | Streamlit |
| Interopérabilité IA | Serveur MCP (Model Context Protocol) |
| Streaming | watchdog + détection d'anomalies (NumPy, z-score) |
| Livrables | openpyxl (Excel), python-pptx (PowerPoint) |
| Données | pandas |

---

## Installation

Prérequis : Python 3.10+.

```bash
# Cloner le dépôt
git clone https://github.com/Nyamey/ai-data-agent.git
cd ai-data-agent

# Créer un environnement virtuel
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate

# Installer les dépendances
pip install -r requirements.txt

# Configurer les clés API
cp .env.example .env
# puis éditez .env avec au moins une clé (Groq, Gemini, OpenRouter ou Mistral)
```

### Configuration

Copiez `.env.example` en `.env` et renseignez au moins une clé API :

```env
GROQ_API_KEY=gsk_votre_cle_ici
GOOGLE_API_KEY=votre_cle_ici
OPENROUTER_API_KEY=sk-or_votre_cle_ici

DEFAULT_LLM_PROVIDER=groq
DEFAULT_LLM_MODEL=llama-3.3-70b-versatile
OUTPUT_LANGUAGE=fr
```

---

## Utilisation

### Interface web (Streamlit)

```bash
streamlit run app.py
```

![Aperçu de l'application Streamlit : upload multi-fichiers, rapport de nettoyage et aperçu des données](docs/screenshot-app.png)

Chargez jusqu'à 5 fichiers CSV, laissez l'application les nettoyer et les analyser (analyse LLM en une passe), puis exportez le résultat en Markdown, CSV, Excel ou PowerPoint. Cette interface est autonome et ne déclenche pas le workflow d'agent en 7 étapes ni l'étape d'approbation — pour cela, utilisez le mode ligne de commande ci-dessous.

### Agent en ligne de commande

```bash
python -m agent.main
```

Cette commande lance directement une démo sur [`data/sample_data.csv`](data/sample_data.csv), un jeu de données synthétique (675 lignes, schéma `customer_id` / `activity_date` / `signup_date` / `platform` / `region` / `segment`) qui simule une vraie baisse de rétention sur les deux dernières semaines côté mobile — reproductible et prêt à l'emploi sans configuration.

Ou dans votre code, avec vos propres données :

```python
from agent.main import run_analysis

run_analysis(
    query="Identifie ce qui explique la récente baisse de rétention client",
    data_path="chemin/vers/vos_donnees.csv",
    language="fr",
)
```

L'agent s'interrompra dans le terminal après l'inspection (invite `oui/non`) pour vous demander d'approuver la poursuite de l'analyse.

### Pipeline de streaming

```python
from agent.streaming.pipeline import StreamingAnalysisPipeline

pipeline = StreamingAnalysisPipeline(watch_dir="./data/stream")
pipeline.start()
```

Déposez un CSV dans le dossier surveillé pour déclencher une analyse automatique. Attention : cela exécute le graphe complet, y compris l'étape d'approbation humaine — le pipeline se bloque donc sur l'invite `input()` du terminal jusqu'à validation manuelle, ce qui est peu adapté à un usage réellement non supervisé (voir [roadmap](#roadmap)).

### Serveur MCP

```bash
python -m mcp_server.server
```

Le serveur expose DuckDB via le Model Context Protocol, ce qui permet à un assistant IA compatible (Claude Desktop, VS Code…) d'interroger directement la base.

---

## Structure du projet

```text
ai-data-agent/
├── agent/
│   ├── graph.py            # Assemblage du graphe LangGraph
│   ├── state.py            # Schéma d'état (Pydantic)
│   ├── main.py             # Point d'entrée de l'agent
│   ├── nodes/              # Les 7 nœuds du workflow
│   ├── tools/              # Chargement de données (DuckDB)
│   ├── llm/                # Config LLM multi-provider + fallback
│   ├── output/             # Générateurs Excel / PPTX (non branchés à l'agent, voir roadmap)
│   └── streaming/          # Surveillance de dossier + détection d'anomalies
├── mcp_server/             # Serveur MCP DuckDB
├── app.py                  # Interface Streamlit
├── docs/                   # Diagramme d'architecture (Mermaid + SVG) et capture d'écran
├── data/
│   └── sample_data.csv     # Jeu de données d'exemple (seul fichier de data/ suivi par git)
├── requirements.txt
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

---

## Roadmap

- [ ] Connecter l'interface Streamlit à l'agent en 7 étapes (aujourd'hui l'app fait une analyse LLM autonome, sans le graphe)
- [ ] Porter l'approbation human-in-the-loop dans l'interface Streamlit (aujourd'hui en CLI via `input()`)
- [ ] Passer à un vrai point d'interruption LangGraph (`interrupt`) plutôt qu'un `input()` bloquant
- [ ] Découpler le pipeline de streaming de l'étape d'approbation bloquante (aujourd'hui incompatible avec un usage non supervisé) et brancher `AnomalyDetector` sur la décision de déclenchement
- [ ] Rendre le calcul de la métrique agnostique au schéma (actuellement orienté rétention client)
- [ ] Tests statistiques complets à l'étape de test (significativité)
- [ ] Brancher les générateurs Excel/PPTX sur la sortie de l'agent
- [x] Jeu de données d'exemple et démo reproductible (`data/sample_data.csv`)
- [ ] Suite de tests automatisés et intégration continue

---

## Licence

Distribué sous licence **MIT**. Voir le fichier [`LICENSE`](LICENSE).

## Auteur

**Karen EKIYABE NYAMEY** — [@Nyamey](https://github.com/Nyamey)
