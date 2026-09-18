import crypto from "crypto";
import type { VisionTransaction } from "./types.js";

/**
 * Normalizes a merchant string for stable deduplication fingerprinting.
 */
export function normalizePayeeForDeduplication(payee: string): string {
  return (payee || "")
    .toLowerCase()
    .replace(/[^\w\s]/g, "") // strip punctuation
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Generates a deterministic imported_id fingerprint for a transaction.
 */
export function generateTransactionFingerprint(tx: {
  date: string;
  amount_cents: number;
  payee: string;
  account_identifier?: string;
}): string {
  const normPayee = normalizePayeeForDeduplication(tx.payee);
  const rawKey = `${tx.date}|${tx.amount_cents}|${normPayee}`;
  return crypto.createHash("sha256").update(rawKey).digest("hex").slice(0, 20);
}

/**
 * Deduplicates a list of vision transactions within a single image or across batch images.
 *
 * Preserves the earliest or most detailed transaction if duplicates occur.
 */
export function deduplicateTransactions(
  transactions: VisionTransaction[]
): {
  uniqueTransactions: VisionTransaction[];
  duplicateCount: number;
  duplicates: VisionTransaction[];
} {
  const seenFingerprints = new Set<string>();
  const uniqueTransactions: VisionTransaction[] = [];
  const duplicates: VisionTransaction[] = [];

  for (const tx of transactions) {
    const fingerprint = tx.imported_id || generateTransactionFingerprint(tx);
    tx.imported_id = fingerprint;

    if (seenFingerprints.has(fingerprint)) {
      duplicates.push(tx);
    } else {
      seenFingerprints.add(fingerprint);
      uniqueTransactions.push(tx);
    }
  }

  return {
    uniqueTransactions,
    duplicateCount: duplicates.length,
    duplicates,
  };
}

/**
 * Filters out transactions that already exist in a given reference ledger or list of transactions.
 */
export function filterExistingTransactions(
  newTransactions: VisionTransaction[],
  existingTransactions: Array<{
    date: string;
    amount?: number;
    amount_cents?: number;
    payee_name?: string;
    payee?: string;
    imported_id?: string;
  }>
): {
  novelTransactions: VisionTransaction[];
  existingCount: number;
} {
  const existingSet = new Set<string>();

  for (const ex of existingTransactions) {
    if (ex.imported_id) {
      existingSet.add(ex.imported_id);
    }
    const cents =
      ex.amount_cents !== undefined
        ? ex.amount_cents
        : ex.amount !== undefined
        ? Math.round(ex.amount)
        : 0;
    const payee = ex.payee_name || ex.payee || "";
    const key = generateTransactionFingerprint({
      date: ex.date,
      amount_cents: cents,
      payee,
    });
    existingSet.add(key);
  }

  const novelTransactions: VisionTransaction[] = [];
  let existingCount = 0;

  for (const tx of newTransactions) {
    const fingerprint = tx.imported_id || generateTransactionFingerprint(tx);
    if (existingSet.has(fingerprint)) {
      existingCount++;
    } else {
      novelTransactions.push(tx);
    }
  }

  return {
    novelTransactions,
    existingCount,
  };
}
