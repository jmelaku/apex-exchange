from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import sqrt


@dataclass
class Observation:
    at: datetime
    event_type: str
    quantity: int
    cancelled: bool


class RiskAnalyzer:
    """Deterministic rolling anomaly detector with no external model dependency."""

    def __init__(self, window_seconds=60, order_rate_threshold=30, cancel_ratio_threshold=0.8):
        self.window = timedelta(seconds=window_seconds)
        self.order_rate_threshold = order_rate_threshold
        self.cancel_ratio_threshold = cancel_ratio_threshold
        self.observations: dict[int, deque[Observation]] = defaultdict(deque)
        self.volume_history: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=500))
        self.last_alert: dict[tuple[int, str], datetime] = {}

    def analyze(self, event: dict, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        account = int(event["account_id"])
        quantity = int(event.get("quantity", 0))
        bucket = self.observations[account]
        bucket.append(Observation(now, event["event_type"], quantity, bool(event.get("cancelled"))))
        while bucket and now - bucket[0].at > self.window:
            bucket.popleft()

        alerts = []
        orders = [item for item in bucket if item.event_type == "ORDER"]
        cancels = [item for item in bucket if item.cancelled or item.event_type == "CANCEL"]
        per_minute = len(orders) * (60 / self.window.total_seconds())
        if per_minute >= self.order_rate_threshold:
            alerts.append(self._event(account, "ORDER_RATE", self._severity(per_minute / self.order_rate_threshold),
                {"orders_in_window": len(orders), "orders_per_minute": round(per_minute, 2),
                 "window_seconds": int(self.window.total_seconds())},
                f"Order rate reached {per_minute:.1f}/minute, above the configured {self.order_rate_threshold}/minute threshold.", now))

        total_actions = len(orders) + len(cancels)
        cancel_ratio = len(cancels) / total_actions if total_actions else 0
        if total_actions >= 10 and cancel_ratio >= self.cancel_ratio_threshold:
            alerts.append(self._event(account, "CANCELLATION_RATE", self._severity(cancel_ratio / self.cancel_ratio_threshold),
                {"cancellations": len(cancels), "actions": total_actions, "cancel_ratio": round(cancel_ratio, 4)},
                f"Cancellation ratio is {cancel_ratio:.0%} across {total_actions} recent actions.", now))

        history = self.volume_history[account]
        if event["event_type"] == "ORDER" and quantity > 0:
            if len(history) >= 20:
                mean = sum(history) / len(history)
                variance = sum((x - mean) ** 2 for x in history) / len(history)
                stddev = sqrt(variance)
                z_score = (quantity - mean) / stddev if stddev else (10.0 if quantity > mean * 3 else 0.0)
                if z_score >= 3:
                    alerts.append(self._event(account, "VOLUME_ANOMALY", self._severity(z_score / 3),
                        {"quantity": quantity, "historical_mean": round(mean, 2),
                         "historical_stddev": round(stddev, 2), "z_score": round(z_score, 2)},
                        f"Order quantity {quantity} is {z_score:.1f} standard deviations above the account baseline.", now))
            history.append(quantity)
        return [alert for alert in alerts if alert is not None]

    def _event(self, account, category, severity, metrics, explanation, now):
        key = (account, category)
        if key in self.last_alert and now - self.last_alert[key] < timedelta(seconds=30):
            return None
        self.last_alert[key] = now
        return {"account_id": account, "category": category, "severity": severity,
                "metrics": metrics, "explanation": explanation, "created_at": now.isoformat()}

    @staticmethod
    def _severity(ratio):
        if ratio >= 3: return "CRITICAL"
        if ratio >= 2: return "HIGH"
        if ratio >= 1.25: return "MEDIUM"
        return "LOW"
