# Post LinkedIn — ai-data-agent

> Format pensé pour LinkedIn : phrases courtes, ligne blanche entre chaque idée (meilleure lisibilité sur mobile et dans le flux). Les deux premières lignes sont l'accroche visible avant le "voir plus" — c'est elles qui décident si on clique.

---

La plupart des outils "IA d'analyse de données" font la même promesse : posez une question, obtenez une réponse en 2 secondes.

Le mien fait l'inverse. Il s'arrête, affiche ce qu'il a compris des données, et attend mon feu vert avant de continuer.

Ce n'est pas un bug de lenteur. C'est le point de départ du projet.

—

J'ai construit **ai-data-agent** pour tester une idée : et si un agent d'analyse de données raisonnait comme un analyste senior plutôt que comme un générateur de SQL ? Un analyste sérieux ne répond pas à une question à l'aveugle — il la cadre, vérifie les données, explicite ses hypothèses avant de calculer quoi que ce soit.

Le projet a deux visages :

🔹 Un **agent en ligne de commande** (LangGraph, 7 étapes : cadrage → inspection → validation humaine → construction → test → validation → recommandations), avec un vrai point de contrôle humain avant que l'analyse ne parte dans une mauvaise direction.

🔹 Une **application Streamlit**, plus simple et immédiate : upload de CSV (jusqu'à 5 fichiers), nettoyage automatique (encodage, formats français, dates, doublons), analyse par LLM, export en Markdown / Excel / PowerPoint.

Les deux s'appuient sur DuckDB pour l'analytique, LiteLLM pour basculer entre plusieurs providers (Groq, Gemini, OpenRouter) si l'un est indisponible, et un serveur MCP qui expose la base à n'importe quel assistant compatible (Claude Desktop, VS Code…).

—

**Ce que j'ai appris en préparant ce projet pour le rendre public :**

Le plus révélateur n'a pas été d'écrire du code — c'est de le relire avec l'intention de le montrer à quelqu'un d'autre.

En préparant cette publication, j'ai trouvé un bug que des jours d'utilisation "pour moi" n'avaient jamais révélé : une inversion silencieuse jour/mois sur certaines dates, visible seulement en générant une vraie capture d'écran avec de vraies données. Le genre de bug qui ne plante rien — il chuchote juste une mauvaise date, et on continue sans s'en apercevoir.

Ça m'a rappelé une évidence : le regard qu'on porte sur son propre code change du tout au tout quand on sait qu'un inconnu va l'exécuter.

—

Le projet est loin d'être fini, et je préfère le dire clairement plutôt que de le maquiller :

— les deux interfaces (agent CLI et app Streamlit) ne sont pas encore connectées entre elles
— le cœur de l'analyse est aujourd'hui pensé pour un cas précis (rétention client), pas encore générique
— pas encore de suite de tests automatisés

C'est un projet en construction active, pas un produit fini. Et c'est exactement pour ça que je le partage maintenant plutôt que d'attendre qu'il soit "parfait".

—

Le code est public, avec un jeu de données d'exemple prêt à l'emploi si vous voulez le lancer en 5 minutes.

Curieuse d'avoir vos retours — surtout si vous avez déjà réfléchi à la place du human-in-the-loop dans des pipelines IA.

🔗 https://github.com/Nyamey/ai-data-agent

---

## Suggestions de hashtags

À adapter selon ta visibilité habituelle — éviter d'en mettre plus de 8-10 pour ne pas paraître spammy :

`#IntelligenceArtificielle` `#DataAnalysis` `#LangGraph` `#Python` `#OpenSource` `#LLM` `#DataEngineering` `#BuildInPublic` `#MachineLearning` `#IA`

## Notes

- Le post ne mentionne pas de démo en ligne (tu as choisi de ne pas inclure le lien Streamlit Cloud) — si tu changes d'avis, ajoute une ligne juste avant le lien GitHub : `🌐 Démo en ligne : [ton lien]`.
- Le paragraphe "ce que j'ai appris" s'appuie sur un bug réel trouvé et corrigé pendant cette session (inversion jour/mois sur les dates ISO dans le nettoyage de données) — pas une anecdote inventée.
- Adapte "Curieuse" en "Curieux" si tu préfères l'accord masculin.
