import { ActualAccount, fetchAccountBalance } from "./actual.js";
import type { StagedImport } from "./matcher.js";

export interface AccountBalanceSummary {
  accountId: string;
  accountName: string;
  currentBalanceCents: number;
  netFlowCents: number;
  projectedBalanceCents: number;
}

export async function calculateAccountBalances(
  stagedImports: StagedImport[],
  accounts: ActualAccount[]
): Promise<AccountBalanceSummary[]> {
  // Collect all unique accounts selected in staged imports that are not skipped
  const activeImports = stagedImports.filter(
    item => item.action === "import" && item.selectedAccount
  );

  const accountMap = new Map<string, ActualAccount>();
  for (const item of activeImports) {
    if (item.selectedAccount) {
      accountMap.set(item.selectedAccount.id, item.selectedAccount);
    }
  }

  const summaries: AccountBalanceSummary[] = [];

  for (const [accountId, account] of accountMap.entries()) {
    let currentBalanceCents = 0;
    try {
      currentBalanceCents = await fetchAccountBalance(accountId);
    } catch {
      currentBalanceCents = 0;
    }

    // Calculate net flow of all staged transactions for this account
    let netFlowCents = 0;
    for (const item of activeImports) {
      if (item.selectedAccount?.id === accountId) {
        const txs = item.statement?.transactions || [];
        for (const t of txs) {
          netFlowCents += t.amount || 0;
        }
      }
    }

    const projectedBalanceCents = currentBalanceCents + netFlowCents;

    summaries.push({
      accountId,
      accountName: account.name,
      currentBalanceCents,
      netFlowCents,
      projectedBalanceCents
    });
  }

  return summaries;
}

export function formatCurrencyCents(cents: number, includeSign = false): string {
  const absDollars = (Math.abs(cents) / 100).toFixed(2);
  if (cents > 0) {
    return includeSign ? `+$${absDollars}` : `$${absDollars}`;
  } else if (cents < 0) {
    return `-$${absDollars}`;
  }
  return `$0.00`;
}

export function formatAccountBalancesTable(
  summaries: AccountBalanceSummary[],
  title = "📊 PROJECTED ACCOUNT BALANCES SUMMARY"
): string {
  if (!summaries || summaries.length === 0) {
    return [
      `┌───────────────────────────────────────────────────────────┐`,
      `│ ${title.padEnd(57)} │`,
      `├───────────────────────────────────────────────────────────┤`,
      `│ (No accounts involved in import)                          │`,
      `└───────────────────────────────────────────────────────────┘`
    ].join("\n");
  }

  const colHeaders = {
    account: "Account Name",
    current: "Current Balance",
    netFlow: "Import Net Flow",
    projected: "Projected Balance"
  };

  const rows = summaries.map(s => ({
    account: s.accountName,
    current: formatCurrencyCents(s.currentBalanceCents),
    netFlow: formatCurrencyCents(s.netFlowCents, true),
    projected: formatCurrencyCents(s.projectedBalanceCents)
  }));

  let wAcc = colHeaders.account.length;
  let wCur = colHeaders.current.length;
  let wNet = colHeaders.netFlow.length;
  let wProj = colHeaders.projected.length;

  for (const r of rows) {
    if (r.account.length > wAcc) wAcc = r.account.length;
    if (r.current.length > wCur) wCur = r.current.length;
    if (r.netFlow.length > wNet) wNet = r.netFlow.length;
    if (r.projected.length > wProj) wProj = r.projected.length;
  }

  const pad = (str: string, width: number) => str.padEnd(width);

  const topBorder    = `┌─${"─".repeat(wAcc)}─┬─${"─".repeat(wCur)}─┬─${"─".repeat(wNet)}─┬─${"─".repeat(wProj)}─┐`;
  const headerRow    = `│ ${pad(colHeaders.account, wAcc)} │ ${pad(colHeaders.current, wCur)} │ ${pad(colHeaders.netFlow, wNet)} │ ${pad(colHeaders.projected, wProj)} │`;
  const headerSep    = `├─${"─".repeat(wAcc)}─┼─${"─".repeat(wCur)}─┼─${"─".repeat(wNet)}─┼─${"─".repeat(wProj)}─┤`;
  const bottomBorder = `└─${"─".repeat(wAcc)}─┴─${"─".repeat(wCur)}─┴─${"─".repeat(wNet)}─┴─${"─".repeat(wProj)}─┘`;

  const lines: string[] = [];
  lines.push(topBorder);
  lines.push(headerRow);
  lines.push(headerSep);
  for (const r of rows) {
    lines.push(`│ ${pad(r.account, wAcc)} │ ${pad(r.current, wCur)} │ ${pad(r.netFlow, wNet)} │ ${pad(r.projected, wProj)} │`);
  }
  lines.push(bottomBorder);

  return lines.join("\n");
}
