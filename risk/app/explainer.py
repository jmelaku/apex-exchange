"""Optional OpenAI-compatible explanations; statistical text is always the fallback."""
import os

import httpx


class RiskExplainer:
    def __init__(self):
        self.api_key = os.getenv("LLM_API_KEY")
        self.base_url = os.getenv("LLM_BASE_URL")
        self.model = os.getenv("LLM_MODEL", "")

    @property
    def enabled(self):
        return bool(self.api_key and self.base_url and self.model)

    async def explain(self, alert: dict) -> str:
        if not self.enabled:
            return alert["explanation"]
        prompt = (
            "Explain this electronic-trading anomaly in two factual sentences. "
            "Do not invent facts. Alert: " + str(alert)
        )
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.post(
                    self.base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "messages": [{"role": "user", "content": prompt}]},
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
        except Exception:
            return alert["explanation"]
