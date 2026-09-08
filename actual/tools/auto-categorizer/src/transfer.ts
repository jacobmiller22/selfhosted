export interface ActualTransaction {
  id: string;
  account: string;
  date: string;
  amount: number;
  payee?: string;
  category?: string;
  imported_payee?: string;
  transferred_id?: string;
  cleared?: boolean;
}

export interface MatchedTransferPair {
  txA: ActualTransaction;
  txB: ActualTransaction;
  dateDeltaDays: number;
}

export function findMatchingTransfers(
  transactions: ActualTransaction[],
  maxDateDeltaDays: number = 3
): MatchedTransferPair[] {
  const matches: MatchedTransferPair[] = [];
  const processedIds = new Set<string>();

  // Filter out transactions already linked as transfers
  const candidates = transactions.filter((t) => !t.transferred_id && t.amount !== 0);

  for (let i = 0; i < candidates.length; i++) {
    const txA = candidates[i];
    if (processedIds.has(txA.id)) continue;

    const dtA = new Date(txA.date).getTime();

    for (let j = i + 1; j < candidates.length; j++) {
      const txB = candidates[j];
      if (processedIds.has(txB.id)) continue;

      // 1. Cross-account check
      if (txA.account === txB.account) continue;

      // 2. Equal and opposite amount check (sum == 0)
      if (txA.amount + txB.amount !== 0) continue;

      // 3. Date window check (|dtA - dtB| <= maxDateDeltaDays)
      const dtB = new Date(txB.date).getTime();
      const deltaDays = Math.abs(dtA - dtB) / (1000 * 60 * 60 * 24);

      if (deltaDays <= maxDateDeltaDays) {
        matches.push({
          txA,
          txB,
          dateDeltaDays: deltaDays
        });

        processedIds.add(txA.id);
        processedIds.add(txB.id);
        break;
      }
    }
  }

  return matches;
}
