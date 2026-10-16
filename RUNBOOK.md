# QuantFlow Production Operations Runbook

This runbook outlines operational procedures for deploying, maintaining, monitoring, and troubleshooting the QuantFlow quantitative trading platform in production.

---

## 1. Production Deployment

### Prerequisites
- Linux host (Ubuntu 22.04 LTS / Debian 12 recommended)
- Docker Engine >= 24.0 & Docker Compose v2 >= 2.20
- Ports 80 and 443 open for inbound traffic (Caddy automatic TLS)
- DNS records (A / CNAME) pointing your domain to the server IP

### Step-by-Step Deployment
1. **Clone repository onto the target host:**
   ```bash
   git clone <REPO_URL> /opt/quantflow
   cd /opt/quantflow
   ```

2. **Configure production environment:**
   ```bash
   cp .env.production.example .env.production
   nano .env.production
   ```
   Set:
   - `DOMAIN`: Your production domain (e.g., `trading.yourdomain.com`)
   - `POSTGRES_PASSWORD`: Strong generated password
   - `REDIS_PASSWORD`: Strong generated password
   - `JWT_SECRET_KEY`: 32+ character cryptographic secret
   - Exchange API keys & secrets (Binance, etc.)

3. **Validate configuration & zero hardcoded values:**
   ```bash
   bash scripts/check-no-hardcoded.sh
   ```

4. **Launch production stack:**
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

5. **Verify health & service status:**
   ```bash
   docker compose -f docker-compose.prod.yml ps
   curl -fsS https://${DOMAIN}/health
   ```
   The health check should return HTTP 200 with `{"status":"ok", "version":"0.1.0", ...}`.

---

## 2. Rollback Procedure

If a deployed revision causes execution anomalies or unhandled errors:

1. **Immediate Circuit Breaker Activation:**
   If live orders are active, trigger the emergency stop immediately from the UI or via REST:
   ```bash
   curl -X POST https://${DOMAIN}/api/v1/risk/emergency-stop \
     -H "Content-Type: application/json" \
     -d '{"enabled": true, "trigger": "ops_rollback"}'
   ```

2. **Revert to Previous Git Tag / Image:**
   ```bash
   git checkout <PREVIOUS_STABLE_TAG>
   docker compose -f docker-compose.prod.yml up -d --build
   ```

3. **Database Migration Downgrade (If schema changed):**
   ```bash
   docker compose -f docker-compose.prod.yml exec app alembic downgrade -1
   ```

4. **Confirm System Health:**
   ```bash
   docker compose -f docker-compose.prod.yml logs -f --tail=100 app
   ```

---

## 3. Secret & Credential Rotation

### Exchange API Keys Rotation
1. Generate new API keys on the exchange dashboard (leave old keys active temporarily).
2. Update `.env.production` with new `BINANCE_API_KEY` and `BINANCE_API_SECRET`.
3. Restart the trading engine container:
   ```bash
   docker compose -f docker-compose.prod.yml restart app
   ```
4. Verify market data and exchange health:
   ```bash
   curl -s https://${DOMAIN}/api/v1/exchanges | jq .
   ```
5. Revoke old API keys on the exchange.

### Database Password Rotation
1. Connect to PostgreSQL and update password:
   ```bash
   docker compose -f docker-compose.prod.yml exec postgres psql -U quantflow_admin -d quantflow \
     -c "ALTER USER quantflow_admin WITH PASSWORD 'NEW_SECURE_PASSWORD';"
   ```
2. Update `POSTGRES_PASSWORD` in `.env.production`.
3. Restart dependent services:
   ```bash
   docker compose -f docker-compose.prod.yml restart app
   ```

---

## 4. Alert Response Procedures

### Alert: `QuantFlowEmergencyStopActive`
- **Severity:** Critical
- **Trigger:** Emergency stop triggered manually or via circuit breaker.
- **Action:**
  1. Inspect `/logs` in dashboard for what tripped the circuit breaker.
  2. Verify exchange open orders are cancelled:
     ```bash
     curl -s https://${DOMAIN}/api/v1/orders?status=NEW
     ```
  3. Resolve the underlying trigger before re-arming risk engine.

### Alert: `QuantFlowExchangeDisconnected`
- **Severity:** High
- **Trigger:** Exchange adapter heartbeat timed out (>30s) or WS closed.
- **Action:**
  1. Verify external exchange status page for outages.
  2. Check app logs: `docker compose -f docker-compose.prod.yml logs --tail=100 app`.
  3. Attempt adapter reconnect toggle via `/api/v1/exchanges/{id}/toggle`.

### Alert: `QuantFlowDrawdownThresholdExceeded`
- **Severity:** High
- **Trigger:** Daily portfolio drawdown exceeds configured `max_daily_loss`.
- **Action:**
  1. Confirm risk engine has halted further order submissions.
  2. Review open positions and market volatility.

---

## 5. Routine Maintenance & Backups

### Automated PostgreSQL Backups (Daily Cron)
Add to system crontab (`crontab -e`):
```bash
0 2 * * * docker compose -f /opt/quantflow/docker-compose.prod.yml exec -T postgres pg_dump -U quantflow_admin quantflow | gzip > /opt/backups/quantflow_$(date +\%F).sql.gz
```

### Redis State Persistence
Redis runs with `appendonly yes` and saves state snapshot to volume `redis_prod_data`.
To trigger manual snapshot:
```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli -a "${REDIS_PASSWORD}" BGSAVE
```
