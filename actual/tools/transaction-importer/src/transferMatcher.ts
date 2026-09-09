import { ActualAccount, ActualPayee, TransactionToImport } from "./actual.js";
import { formatCurrencyCents } from "./balances.js";
import type { StagedImport } from "./matcher.js";
import { OnnxPredictorEngine } from "./predictor.js";

export interface MatchedTransferPair {
  importIndexA: number;
  txIndexA: number;
  filenameA: string;
  accountA: ActualAccount;
  txA: TransactionToImport;

  importIndexB: number;
  txIndexB: number;
  filenameB: string;
  accountB: ActualAccount;
  txB: TransactionToImport;

  dateDeltaDays: number;
  confidence: number;
  matchReason: string;
}

export interface DetectTransfersOptions {
  maxDateDeltaDays?: number;
  enablePredictor?: boolean;
  predictorEngine?: OnnxPredictorEngine;
}

const TRANSFER_KEYWORDS = [
  "transfer",
  "xfr",
  "webxfr",
  "pmt",
  "payment",
  "ach",
  "mobile pmt",
  "deposit",
  "withdrawal",
  "checking",
  "savings",
  "brokerage",
  "zelle",
  "venmo",
  "online transfer",
  "tfr",
  "wire transfer"
];

function hasTransferKeyword(text?: string): boolean {
  if (!text) return false;
  const lower = text.toLowerCase();
  return TRANSFER_KEYWORDS.some(kw => lower.includes(kw));
}

interface FlattenedTx {
  importIndex: number;
  txIndex: number;
  filename: string;
  account: ActualAccount;
  tx: TransactionToImport;
}

export async function detectIntraBatchTransferPairs(
  stagedImports: StagedImport[],
  payees: ActualPayee[],
  options: DetectTransfersOptions = {}
): Promise<MatchedTransferPair[]> {
  const maxDateDelta = options.maxDateDeltaDays ?? 5;
  const predictor = options.predictorEngine;

  // Build mapping: accountId -> transfer payee ID
  const accountTransferPayeeMap = new Map<string, ActualPayee>();
  for (const p of payees) {
    if (p.transfer_acct) {
      accountTransferPayeeMap.set(p.transfer_acct, p);
    }
  }

  // Flatten active staged transactions
  const items: FlattenedTx[] = [];
  for (let i = 0; i < stagedImports.length; i++) {
    const item = stagedImports[i];
    if (item.action !== "import" || !item.selectedAccount) continue;

    const txs = item.statement?.transactions || [];
    for (let j = 0; j < txs.length; j++) {
      items.push({
        importIndex: i,
        txIndex: j,
        filename: item.filename,
        account: item.selectedAccount,
        tx: txs[j]
      });
    }
  }

  interface MatchCandidate {
    itemA: FlattenedTx;
    itemB: FlattenedTx;
    dateDeltaDays: number;
    confidence: number;
    reason: string;
  }

  const candidates: MatchCandidate[] = [];

  for (let i = 0; i < items.length; i++) {
    const itemA = items[i];
    if (itemA.tx.amount === 0) continue;

    const dtA = Date.parse(itemA.tx.date);
    if (isNaN(dtA)) continue;

    for (let j = i + 1; j < items.length; j++) {
      const itemB = items[j];
      if (itemB.tx.amount === 0) continue;

      // 1. Cross-account requirement
      if (itemA.account.id === itemB.account.id) continue;

      // 2. Equal and opposite amount check
      if (itemA.tx.amount + itemB.tx.amount !== 0) continue;

      // 3. Date window check
      const dtB = Date.parse(itemB.tx.date);
      if (isNaN(dtB)) continue;

      const dateDeltaDays = Math.abs(dtA - dtB) / (1000 * 60 * 60 * 24);
      if (dateDeltaDays > maxDateDelta) continue;

      // Calculate confidence & reason
      let confidence = 0.70; // baseline for cross-account opposite amount within date window
      const reasons: string[] = [`equal/opposite amount (${formatCurrencyCents(Math.abs(itemA.tx.amount))})`];

      if (dateDeltaDays === 0) {
        confidence += 0.15;
        reasons.push("same date");
      } else {
        reasons.push(`${dateDeltaDays.toFixed(0)}d date diff`);
      }

      const textA = itemA.tx.payee_name || itemA.tx.notes || "";
      const textB = itemB.tx.payee_name || itemB.tx.notes || "";

      if (hasTransferKeyword(textA) || hasTransferKeyword(textB)) {
        confidence += 0.10;
        reasons.push("transfer keyword matched");
      }

      // Check ONNX predictor model if available
      if (predictor && predictor.isInitialized()) {
        const predA = await predictor.predictPayee(textA, itemA.account.id, itemA.tx.amount);
        const targetPayeeB = accountTransferPayeeMap.get(itemB.account.id);
        if (predA && targetPayeeB && predA.label === targetPayeeB.id && predA.confidence > 0.5) {
          confidence += 0.15;
          reasons.push(`ML predicted transfer to ${itemB.account.name} (${(predA.confidence * 100).toFixed(0)}% conf)`);
        }
      }

      confidence = Math.min(1.0, confidence);

      candidates.push({
        itemA,
        itemB,
        dateDeltaDays,
        confidence,
        reason: reasons.join(", ")
      });
    }
  }

  // Sort candidates by highest confidence, then smallest date delta
  candidates.sort((a, b) => {
    if (b.confidence !== a.confidence) {
      return b.confidence - a.confidence;
    }
    return a.dateDeltaDays - b.dateDeltaDays;
  });

  const matchedPairs: MatchedTransferPair[] = [];
  const processedKeys = new Set<string>();

  for (const c of candidates) {
    const keyA = `${c.itemA.importIndex}:${c.itemA.txIndex}`;
    const keyB = `${c.itemB.importIndex}:${c.itemB.txIndex}`;

    if (processedKeys.has(keyA) || processedKeys.has(keyB)) {
      continue;
    }

    processedKeys.add(keyA);
    processedKeys.add(keyB);

    // Link transactions to Transfer Payees in Actual Budget
    const transferPayeeForB = accountTransferPayeeMap.get(c.itemB.account.id);
    const transferPayeeForA = accountTransferPayeeMap.get(c.itemA.account.id);

    if (transferPayeeForB) {
      c.itemA.tx.payee = transferPayeeForB.id;
    }
    if (transferPayeeForA) {
      c.itemB.tx.payee = transferPayeeForA.id;
    }

    matchedPairs.push({
      importIndexA: c.itemA.importIndex,
      txIndexA: c.itemA.txIndex,
      filenameA: c.itemA.filename,
      accountA: c.itemA.account,
      txA: c.itemA.tx,

      importIndexB: c.itemB.importIndex,
      txIndexB: c.itemB.txIndex,
      filenameB: c.itemB.filename,
      accountB: c.itemB.account,
      txB: c.itemB.tx,

      dateDeltaDays: c.dateDeltaDays,
      confidence: c.confidence,
      matchReason: c.reason
    });
  }

  return matchedPairs;
}

export function formatTransferPairsSummary(pairs: MatchedTransferPair[]): string {
  if (!pairs || pairs.length === 0) {
    return [
      `┌───────────────────────────────────────────────────────────┐`,
      `│ 🔄 IDENTIFIED PAIRED TRANSFERS                             │`,
      `├───────────────────────────────────────────────────────────┤`,
      `│ (No intra-batch paired transfers detected)                │`,
      `└───────────────────────────────────────────────────────────┘`
    ].join("\n");
  }

  const lines: string[] = [];
  lines.push(`┌─────────────────────────────────────────────────────────────┐`);
  lines.push(`│ 🔄 IDENTIFIED PAIRED TRANSFERS (${pairs.length} pair${pairs.length === 1 ? "" : "s"} linked)             │`);
  lines.push(`├─────────────────────────────────────────────────────────────┤`);

  for (let i = 0; i < pairs.length; i++) {
    const p = pairs[i];
    const amountStr = formatCurrencyCents(Math.abs(p.txA.amount));
    const deltaStr = p.dateDeltaDays === 0 ? "same day" : `${p.dateDeltaDays.toFixed(0)}d diff`;
    const confPct = `${(p.confidence * 100).toFixed(0)}%`;

    lines.push(`│ Pair #${i + 1}: ${amountStr} Transfer [Confidence: ${confPct}]`);
    lines.push(`│   • Side A: ${p.accountA.name} (${p.filenameA}) - ${p.txA.date} [${formatCurrencyCents(p.txA.amount, true)}]`);
    lines.push(`│   • Side B: ${p.accountB.name} (${p.filenameB}) - ${p.txB.date} [${formatCurrencyCents(p.txB.amount, true)}]`);
    lines.push(`│   • Details: ${p.matchReason} (${deltaStr})`);
    if (i < pairs.length - 1) {
      lines.push(`├─────────────────────────────────────────────────────────────┤`);
    }
  }

  lines.push(`└─────────────────────────────────────────────────────────────┘`);
  return lines.join("\n");
}
