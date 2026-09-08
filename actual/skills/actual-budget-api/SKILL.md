---
name: actual-budget-api
description: Guide and best practices for integrating with Actual Budget via @actual-app/api Node.js SDK and REST endpoints.
---

# Actual Budget API Integration Skill

This skill documents how to interact with Actual Budget programmatically using `@actual-app/api` in Node.js/TypeScript sidecars and automated background services.

## Core Concepts & Architectural Enforcements

### 1. Server URL Normalization & HTTPS FQDN
Actual Budget requires binary sync header validation when clients connect to its server. 
- **Requirement**: `serverURL` must resolve to the public HTTPS FQDN (e.g., `https://budget.cloud.jacobmiller22.com`).
- **Internal Docker Routing**: If the daemon runs inside a Docker network alongside `actual_server`, normalize `SERVER_URL` to ensure sync headers match the expected public host.

```typescript
let SERVER_URL = process.env.ACTUAL_SERVER_URL || "https://budget.cloud.jacobmiller22.com";
if (SERVER_URL.includes("actual_server")) {
  SERVER_URL = "https://budget.cloud.jacobmiller22.com";
}
```

### 2. SQLite Cache Initialization & Cleanup
`@actual-app/api` uses a local SQLite cache directory (`.actual-cache`) to download and sync the budget file.
- **Cache Lock Contention**: Prior to invoking `api.init()`, purge and recreate the cache directory to prevent file lock contention or stale SQLite locks across daemon restarts.

```typescript
export async function connectActual(
  serverUrl: string,
  password: string,
  syncId: string,
  dataDir?: string
): Promise<void> {
  const cacheDir = dataDir || path.resolve(process.cwd(), ".actual-cache");
  if (fs.existsSync(cacheDir)) {
    fs.rmSync(cacheDir, { recursive: true, force: true });
  }
  fs.mkdirSync(cacheDir, { recursive: true });

  await api.init({
    dataDir: cacheDir,
    serverURL: serverUrl,
    password: password
  });

  await api.downloadBudget(syncId);
}
```

### 3. Transaction Updates & Schema Rules
When updating transaction properties via `api.updateTransaction(id, updates)`:
- **Required `account` Field**: The internal `transactions` schema validator in `@actual-app/api` enforces that the `account` property must be included in update payloads. Omission will trigger a schema error:
  `Error: "account" is required for table "transactions"`.
- **Field Naming**: Use `transfer_id` (not `transferred_id`) for cross-account transfer links.
- **Payload Structure**:
  ```typescript
  await api.updateTransaction(transactionId, {
    account: tx.account,
    category: categoryUuid,
    payee: payeeUuid,
    notes: "[ML Suggestion: Subscriptions (88%)]",
    transfer_id: matchingTxId
  });
  ```

### 4. Handling Split Transactions (`is_parent` / `is_child`)
- **Parent Transactions**: Split parent transactions (`is_parent: true`) have `category: null` because individual split subtransactions (`is_child: true`) hold the category assignments.
- **Rule**: Do **NOT** pass split parent transactions (`is_parent: true`) to category update APIs or ML auto-categorization loops. Updating a split parent's category field causes `@actual-app/api` to recalculate subtransactions and issue partial diffs lacking `account`, crashing the sync process.

```typescript
// Filter out split parents and split children prior to ML inference
const uncategorizedTxs = transactions.filter(
  (t) => !t.category && !t.transfer_id && !t.is_parent && !t.is_child
);
```

---

## Dataset Export for ML Training

To extract historical categorized transactions for model training:

```javascript
const rawTxs = await api.getTransactions();
const payees = await api.getPayees();
const payeeMap = new Map((payees || []).map((p) => [p.id, p.name]));

const records = [];
function processTx(t) {
  if (t.category && !t.transfer_id) {
    const payeeName = payeeMap.get(t.payee) || "";
    const rawPayee = t.imported_payee || t.payee_name || payeeName || t.notes || "";
    if (rawPayee) {
      records.push({
        id: t.id,
        date: t.date,
        amount: t.amount,
        account_id: t.account,
        imported_payee: rawPayee,
        payee_id: t.payee || "unmapped_payee",
        category_id: t.category,
        is_transfer: false
      });
    }
  }
  if (t.subtransactions) {
    t.subtransactions.forEach(processTx);
  }
}

(rawTxs || []).forEach(processTx);
```
