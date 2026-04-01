---
name: er-query
description: Query Expert Request (ER) data from Google Cloud Firestore using an MCP server. Use when users ask about ERs, customer engagements, FSA status, workload tracking, or need to look up specific ER fields by name, email, or date.
---

# Expert Request (ER) Query Skill

## Overview

This skill enables you to query Expert Request (ER) data from a Firestore-backed MCP server. ERs track customer engineering engagements including account details, FSA status, workload revenue, and engagement metadata.

## Prerequisites

Before querying ER data, follow these steps:

1. **Verify the ER MCP server is connected** — check that the `er-query` MCP server is listed and available in your MCP client.
2. **If not connected**, check whether the Cloud Run proxy is running:
   ```bash
   gcloud run services proxy er-mcp-server --region us-central1 --port=3000
   ```
   If it is not running, start it in a separate terminal. This makes the MCP server available at `http://127.0.0.1:3000`.
3. GCP credentials with Firestore access to the `expert_requests_dev` collection must be configured.

## MCP Server Setup (Cloud Run Proxy)

First, start the Cloud Run proxy in a separate terminal:

```bash
gcloud run services proxy er-mcp-server --region us-central1 --port=3000
```

Then configure your MCP client (e.g., `cline_mcp_settings.json`, `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "er-query": {
      "url": "http://127.0.0.1:3000/sse"
    }
  }
}
```

## Available Tools

### 1. `search_er_by_email`

Search ERs assigned to a specific Customer Engineer by email.

**When to use:** User asks about ERs assigned to a person (e.g., "show me ERs for issein@google.com", "what ERs does Wei Yih have?")

**Parameters:**
- `assigned_ce_email` (string, required): Google corporate email (e.g., `issein@google.com`)

**Returns:** JSON list of ER summaries with: `er_name`, `account_name`, `account_sub_region`, `assigned_ce_email`, `details`

### 2. `search_er_by_date`

Search ERs by creation date.

**When to use:** User asks about ERs from a time period (e.g., "show me ERs from 2025", "what ERs were created in October 2025?")

**Parameters:**
- `year` (integer, required): Year to filter by (e.g., 2025)
- `month` (integer, optional): Month 1-12. Omit to search entire year.

**Returns:** JSON list of ER summaries (same fields as above)

### 3. `get_er_fields`

Get specific fields from an ER by its name.

**When to use:** User asks about a specific ER and wants particular fields (e.g., "for ER-431059, show me the fsa_status", "what's the workload revenue for ER-431059?")

**Parameters:**
- `er_name` (string, required): ER identifier with prefix (e.g., `ER-431059`)
- `fields` (string, optional): Comma-separated field names. Omit to return all fields.

**Common field names:**

| Category | Fields |
|----------|--------|
| Basic | `er_name`, `account_name`, `status`, `product`, `details`, `priority` |
| FSA | `fsa_status`, `fsa_assets`, `fsa_flight_status`, `fsa_start_date`, `fsa_end_date`, `fsa_status_tracking`, `fsa_weekly_update`, `fsa_workload_gross_revenue_tracking`, `fsa_workload_progress_tracking` |
| Workload | `workload_name`, `workload_gross_revenue`, `workload_gross_revenue_tracking`, `workload_progress`, `workload_pillar`, `workload_solution`, `workload_progress_tracking` |
| People | `assigned_ce_email`, `assigned_ce_name`, `requestor_name`, `requestor_email` |
| Opportunity | `opportunity_name`, `opportunity_amount`, `opportunity_stage_name` |
| Engagement | `engagement_type`, `engagement_tier`, `engagement_priority` |

**Returns:** JSON list with `er_name` plus requested fields. Missing fields return `null`.

## Field Name Mapping

Users may use informal names. Map them to actual field names:

| User says | Actual field |
|-----------|-------------|
| "fsa asset", "fsa assets" | `fsa_assets` |
| "fsa status" | `fsa_status` |
| "workload revenue", "gross revenue" | `workload_gross_revenue` |
| "revenue tracking" | `workload_gross_revenue_tracking` |
| "workload name" | `workload_name` |
| "flight status" | `fsa_flight_status` |
| "opportunity amount", "deal size" | `opportunity_amount` |

## Example Queries

### By email
```
User: "Show me ERs assigned to issein@google.com"
Action: Call search_er_by_email(assigned_ce_email="issein@google.com")
```

### By date
```
User: "What ERs were created in October 2025?"
Action: Call search_er_by_date(year=2025, month=10)
```

### Specific ER fields
```
User: "For ER-431059, show me the fsa_assets and fsa_status"
Action: Call get_er_fields(er_name="ER-431059", fields="fsa_assets,fsa_status")

User: "Show me workload info for ER-431059"
Action: Call get_er_fields(er_name="ER-431059", fields="workload_name,workload_gross_revenue,workload_gross_revenue_tracking")

User: "Show me everything about ER-431059"
Action: Call get_er_fields(er_name="ER-431059") (no fields = return all)
```

## Response Formatting

- Present ER data in a clean, readable format
- For lists of ERs, show count and highlight key info (ER name, account, status)
- For field queries, format complex fields (arrays, nested objects) readably
- For revenue fields, format as currency (e.g., `$1,920,000.00`)
- If no results found, clearly state that
