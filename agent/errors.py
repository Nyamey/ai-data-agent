# agent/errors.py — Erreurs applicatives avec message utilisateur séparé du détail technique
class UserFacingError(Exception):
    """Base pour toute erreur applicative destinée à être affichée à l'utilisateur.

    Sépare le message utilisateur (clair, actionnable, sans jargon) du détail
    technique (traces brutes, SQL généré, noms de table internes) -- ce
    dernier n'a sa place que dans les logs serveur, jamais à l'écran, où il
    n'aide personne et expose des détails d'implémentation (confirmé par un
    retour utilisateur sur une trace DuckDB affichée telle quelle).

    `severity` indique comment l'appelant (l'UI) doit présenter l'erreur :
    - "warning" : situation temporaire, pas la faute de l'utilisateur ni un
      vrai blocage (ex. quota LLM épuisé -- attendre suffit).
    - "error" : nécessite une action de l'utilisateur pour continuer (ex.
      reconfigurer une jointure).
    Les sous-classes fixent leur propre défaut ; str(exception) combine
    toujours les deux messages pour les appelants qui ne font pas la
    distinction (CLI, logs, anciens tests).
    """

    severity = "error"

    def __init__(self, user_message: str, technical_detail: str = None):
        super().__init__(
            f"{user_message} Détail technique : {technical_detail}"
            if technical_detail else user_message
        )
        self.user_message = user_message
        self.technical_detail = technical_detail
