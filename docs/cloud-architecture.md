# Cloud deployment mapping

The local topology maps cleanly to any major cloud without requiring cloud resources for
development.

| Local component | AWS example | Azure example | GCP example |
|---|---|---|---|
| frontend nginx | S3 + CloudFront | Storage + Front Door | Cloud Storage + CDN |
| FastAPI / risk | ECS/EKS | Container Apps/AKS | Cloud Run/GKE |
| matching engine | dedicated ECS/EC2 placement | dedicated VMSS/AKS node | dedicated GCE/GKE node |
| PostgreSQL | RDS PostgreSQL | Azure Database for PostgreSQL | Cloud SQL |
| outbox/event fanout | MSK/SNS/SQS | Event Hubs/Service Bus | Pub/Sub |
| metrics/logs | CloudWatch/AMP | Monitor/Managed Prometheus | Cloud Monitoring |

For production, partition symbols across matching-engine leaders. A replicated command log
would assign sequence numbers, replay books after restart, and allow API replicas to route
to the partition leader. Settlement consumers would be idempotent on engine trade ID. The
transactional outbox would publish after commit, with consumers deduplicating by event ID.

Run the engine on isolated compute with CPU pinning, predictable instance types, placement
control, and load balancers used only for control-plane health—not per-order random routing.
Put APIs across availability zones, use a managed PostgreSQL primary with synchronous
standby and point-in-time recovery, and keep the database private. Use workload identity,
a secrets manager, mTLS, encryption at rest, WAF/rate limiting, audit trails, and separate
operator/customer authorization.

Autoscale stateless API/risk consumers on latency and queue lag. Engine partitions scale by
symbol reassignment rather than arbitrary replicas. Track match latency separately from
end-to-end settlement latency. Disaster recovery requires regular book snapshots plus the
ordered command log and reconciliation against the durable trade ledger.
