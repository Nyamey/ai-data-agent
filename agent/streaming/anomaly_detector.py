# agent/streaming/anomaly_detector.py — Détection d'anomalies simple
import numpy as np
from collections import deque


class AnomalyDetector:
    """
    Détecte les anomalies dans un flux de données.
    
    Utilise le z-score (écart à la moyenne en nombre d'écarts-types).
    Si une valeur s'écarte de plus de 2 écarts-types, c'est une anomalie.
    """
    
    def __init__(self, window_size: int = 12, threshold: float = 2.0):
        """
        Args:
            window_size: Nombre de valeurs à garder en mémoire pour la comparaison
            threshold: Seuil de détection (2.0 = 2 écarts-types)
        """
        self.window_size = window_size
        self.threshold = threshold
        self.history = deque(maxlen=window_size)
    
    def update(self, value: float) -> dict:
        """
        Met à jour le détecteur avec une nouvelle valeur.
        
        Returns:
            Dictionnaire avec le statut d'anomalie et les statistiques.
        """
        self.history.append(value)
        
        # Il faut au moins 3 valeurs pour calculer un z-score
        if len(self.history) < 3:
            return {"anomaly": False, "value": value, "reason": "pas_assez_de_donnees"}
        
        # Calculer la moyenne et l'écart-type
        mean = np.mean(self.history)
        std = np.std(self.history)
        
        if std == 0:
            return {"anomaly": False, "value": value, "reason": "pas_de_variance"}
        
        # Calculer le z-score
        z_score = (value - mean) / std
        is_anomaly = bool(abs(z_score) > self.threshold)
        
        return {
            "anomaly": is_anomaly,
            "value": value,
            "moyenne": round(mean, 4),
            "ecart_type": round(std, 4),
            "z_score": round(z_score, 4),
            "direction": "hausse" if z_score > 0 else "baisse",
            "severite": (
                "elevee" if abs(z_score) > 3 
                else "moyenne" if abs(z_score) > 2 
                else "faible"
            ),
        }
