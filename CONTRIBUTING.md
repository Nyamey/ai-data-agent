# Contribuer à ai-data-agent

Merci de votre intérêt pour le projet ! Les contributions sont les bienvenues, qu'il s'agisse de corrections de bugs, de nouvelles fonctionnalités, de tests ou d'améliorations de la documentation.

## Mise en place de l'environnement

```bash
git clone https://github.com/Nyamey/ai-data-agent.git
cd ai-data-agent
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # renseignez au moins une clé API
```

## Workflow de contribution

1. **Forkez** le dépôt et créez une branche à partir de `main` :

   ```bash
   git checkout -b feat/ma-fonctionnalite
   ```

2. Faites vos modifications avec des commits clairs et atomiques.
3. Vérifiez que le projet démarre (`streamlit run app.py`, `python -m agent.main`) et que la suite de tests passe (`python -m pytest tests/ -v`) ; la CI GitHub Actions la relance automatiquement sur la Pull Request.
4. Poussez votre branche et ouvrez une **Pull Request** vers `main`.
5. Décrivez le *pourquoi* de votre changement, pas seulement le *quoi*.

## Conventions

- **Style** : suivez la PEP 8. Des noms de variables explicites en français ou en anglais, mais restez cohérent avec le fichier modifié.
- **Commits** : privilégiez le format [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `refactor:`…).
- **Docstrings** : documentez les nouveaux nœuds et outils comme les existants (rôle, entrées, sorties).
- **Secrets** : ne committez jamais de `.env` ni de clés API. Le `.gitignore` les exclut déjà.

## Idées de contributions

Toutes les étapes de la [roadmap du README](README.md#roadmap) sont complétées. Pistes ouvertes pour la suite :

- Couvrir les nœuds `framing`/`recommend` (qui appellent un LLM) par des tests automatisés, via un provider local/déterministe.
- Analyse jointe entre plusieurs fichiers liés, au-delà des cycles indépendants actuels du mode agent multi-fichiers.
- Export des livrables (Excel/PowerPoint) depuis le pipeline de streaming.

## Signaler un bug

Ouvrez une [issue](https://github.com/Nyamey/ai-data-agent/issues) en décrivant :

- ce que vous attendiez et ce qui s'est produit,
- les étapes pour reproduire,
- votre version de Python et le provider LLM utilisé.

## Licence

En contribuant, vous acceptez que votre contribution soit distribuée sous licence MIT.
