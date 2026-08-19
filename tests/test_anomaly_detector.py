# tests/test_anomaly_detector.py : détection d'anomalies par z-score
from agent.streaming.anomaly_detector import AnomalyDetector


def test_needs_at_least_three_points_before_judging():
    d = AnomalyDetector()
    assert d.update(100)["reason"] == "pas_assez_de_donnees"
    assert d.update(102)["reason"] == "pas_assez_de_donnees"


def test_flags_no_variance_once_history_is_constant():
    d = AnomalyDetector()
    d.update(100)
    d.update(100)
    result = d.update(100)
    assert result["anomaly"] is False
    assert result["reason"] == "pas_de_variance"


def test_detects_upward_anomaly():
    d = AnomalyDetector(window_size=12, threshold=2.0)
    for _ in range(10):
        d.update(100)
    result = d.update(1000)
    assert result["anomaly"] is True
    assert result["direction"] == "hausse"


def test_detects_downward_anomaly():
    d = AnomalyDetector(window_size=12, threshold=2.0)
    for _ in range(10):
        d.update(100)
    result = d.update(1)
    assert result["anomaly"] is True
    assert result["direction"] == "baisse"


def test_normal_variation_is_not_flagged():
    d = AnomalyDetector(window_size=12, threshold=2.0)
    values = [100, 102, 98, 101, 99, 103, 97, 100, 102, 99]
    for v in values:
        d.update(v)
    result = d.update(101)
    assert result["anomaly"] is False


def test_window_size_limits_history():
    d = AnomalyDetector(window_size=5)
    for v in range(20):
        d.update(v)
    assert len(d.history) == 5
