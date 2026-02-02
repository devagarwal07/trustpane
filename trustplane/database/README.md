# TrustPlane Database Setup

## Overview

This directory contains SQL migrations for setting up the TrustPlane database in Supabase.

## Prerequisites

1. Create a Supabase project at [supabase.com](https://supabase.com)
2. Get your project URL and keys from Settings > API

## Migration Order

Run these migrations **in order** in the Supabase SQL Editor:

```
1. 001_initial_schema.sql      - Tables, indexes, functions
2. 002_row_level_security.sql  - RLS policies for multi-tenancy
3. 003_seed_data.sql           - System permissions & role setup
4. 004_realtime_subscriptions.sql - Realtime for live updates
```

## Quick Setup

1. Go to Supabase Dashboard > SQL Editor
2. Copy and paste each file in order
3. Click "Run" for each

## Key Tables

| Table | Purpose |
|-------|---------|
| `organizations` | Tenants (companies) |
| `users` | User accounts within orgs |
| `events` | Immutable event ledger (event sourcing) |
| `workflows` | Workflow instances |
| `sla_definitions` | SLA templates |
| `sla_instances` | Active SLAs on workflows |
| `sla_breaches` | Breach records |
| `audit_logs` | Compliance audit trail |
| `agent_decisions` | AI agent outputs |
| `policies` | ABAC policies |
| `roles` | RBAC roles |

## Row Level Security (RLS)

All tables have RLS enabled with org-based isolation:

```sql
-- Example: Users can only see data in their organization
USING (org_id = auth.org_id())
```

The `auth.org_id()` function extracts the organization ID from the JWT claims.

## JWT Claims Structure

Your Supabase JWT should include:

```json
{
  "sub": "user-uuid",
  "org_id": "organization-uuid",
  "role": "admin|manager|member|viewer",
  "email": "user@example.com"
}
```

## Immutable Tables

These tables are **append-only** (no UPDATE/DELETE):

- `events` - Event ledger
- `audit_logs` - Audit trail
- `sla_breaches` - Breach records

## Event Sourcing

The `events` table is hash-chained for tamper detection:

```sql
hash = SHA256(previous_hash + event_data)
```

Verify integrity with:
```sql
SELECT * FROM events 
WHERE stream_id = 'workflow-uuid' 
ORDER BY version;
```

## Realtime Subscriptions

Enabled for live dashboard updates:
- `workflows` - State changes
- `sla_instances` - SLA status
- `sla_breaches` - Breach alerts
- `agent_decisions` - AI decisions

## Useful Queries

### Check active SLAs at risk
```sql
SELECT * FROM sla_instances 
WHERE status = 'active' 
AND soft_deadline < NOW() + INTERVAL '1 hour'
ORDER BY soft_deadline;
```

### Get workflow event timeline
```sql
SELECT * FROM events 
WHERE stream_id = 'workflow-uuid' 
ORDER BY version;
```

### Verify event chain integrity
```sql
-- Will be handled by application layer
```

### SLA compliance rate
```sql
SELECT 
  COUNT(*) FILTER (WHERE status = 'met') as met,
  COUNT(*) FILTER (WHERE status IN ('soft_breach', 'hard_breach')) as breached,
  COUNT(*) as total,
  ROUND(
    COUNT(*) FILTER (WHERE status = 'met')::numeric / 
    NULLIF(COUNT(*), 0) * 100, 2
  ) as compliance_rate
FROM sla_instances
WHERE org_id = 'your-org-uuid';
```

## Maintenance

### Backup Events Table
Events are immutable - regular backups are critical:

```sql
-- Export events for backup
COPY (SELECT * FROM events WHERE org_id = 'uuid') 
TO '/tmp/events_backup.csv' WITH CSV HEADER;
```

### Index Maintenance
The event store can grow large. Monitor index usage:

```sql
SELECT 
  schemaname, tablename, indexname, 
  idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes 
WHERE tablename = 'events';
```
