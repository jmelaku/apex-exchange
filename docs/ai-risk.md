# Risk and anomaly detection

The risk service is activity analysis, not a chatbot. After a trading commit, the API sends
the account, symbol, action, side, quantity, cancellation flag, and trade count. The
`RiskAnalyzer` maintains a time-pruned deque per account plus a bounded quantity history.

It currently detects:

- order rate at or above a configurable per-minute threshold;
- cancellation ratio above a threshold after at least ten actions;
- order volume at least three standard deviations above an account baseline after twenty
  observations.

Severity derives from threshold multiple. A 30-second account/category cooldown prevents
alert floods. Every alert includes supporting numeric metrics and deterministic explanatory
text and is inserted into PostgreSQL before being returned for WebSocket publication.

`risk/app/explainer.py` is an optional OpenAI-compatible adapter. It activates only when
`LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` are all configured, applies a short timeout,
and always falls back to the statistical explanation. No key, remote service, or paid API
is needed for detection or for the rest of APEX.

Unit tests cover threshold activation, alert cooldown, cancellation behavior, and a clear
z-score anomaly. Metrics are exposed at `/metrics`; health reports the baseline model and
whether optional explanation is configured.
