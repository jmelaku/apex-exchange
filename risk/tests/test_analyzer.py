from datetime import datetime, timedelta, timezone

from risk.app.analyzer import RiskAnalyzer


def event(quantity=10, kind="ORDER", cancelled=False):
    return {"event_type": kind, "account_id": 7, "symbol": "AAPL", "quantity": quantity, "cancelled": cancelled}


def test_order_rate_alert_and_cooldown():
    analyzer = RiskAnalyzer(window_seconds=60, order_rate_threshold=3)
    now = datetime.now(timezone.utc)
    assert analyzer.analyze(event(), now) == []
    assert analyzer.analyze(event(), now + timedelta(seconds=1)) == []
    alerts = analyzer.analyze(event(), now + timedelta(seconds=2))
    assert alerts[0]["category"] == "ORDER_RATE"
    assert analyzer.analyze(event(), now + timedelta(seconds=3)) == []


def test_volume_z_score_anomaly():
    analyzer = RiskAnalyzer(order_rate_threshold=10_000)
    now = datetime.now(timezone.utc)
    for index in range(20):
        analyzer.analyze(event(10 + index % 2), now + timedelta(seconds=index))
    alerts = analyzer.analyze(event(1000), now + timedelta(seconds=25))
    assert any(alert["category"] == "VOLUME_ANOMALY" for alert in alerts)


def test_cancellation_ratio():
    analyzer = RiskAnalyzer(order_rate_threshold=10_000, cancel_ratio_threshold=0.7)
    now = datetime.now(timezone.utc)
    alerts = []
    for index in range(10):
        alerts += analyzer.analyze(event(kind="CANCEL", cancelled=True), now + timedelta(seconds=index))
    assert any(alert["category"] == "CANCELLATION_RATE" for alert in alerts)
