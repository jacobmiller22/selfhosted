import { TransactionToImport } from '../actual.js';
import type { CsvProfile } from '../config.js';

export interface AccountStatement {
  accountNumber?: string;
  transactions: TransactionToImport[];
  detectedHeaders?: CsvProfile;
  csvHeaders?: string[];
}

export interface ParsedStatement {
  accountStatements: AccountStatement[];
}

export function parseOfxContent(content: string): ParsedStatement {
  const responseBlockRegex = /<(?:STMTTRNRS|CCSTMTTRNRS)>/gi;
  const matches = Array.from(content.matchAll(responseBlockRegex));

  const rawBlocks: string[] = [];
  if (matches.length > 0) {
    for (let i = 0; i < matches.length; i++) {
      const startIndex = matches[i].index! + matches[i][0].length;
      const endIndex = i + 1 < matches.length ? matches[i + 1].index! : content.length;
      rawBlocks.push(content.substring(startIndex, endIndex));
    }
  } else {
    rawBlocks.push(content);
  }

  const accountStatements: AccountStatement[] = [];

  for (const block of rawBlocks) {
    let accountNumber: string | undefined;
    const acctMatch = block.match(/<ACCTID>([^<\r\n]+)/i);
    if (acctMatch) {
      accountNumber = acctMatch[1].trim();
    }

    const trnBlocks = block.split(/<STMTTRN>/i).slice(1);
    const transactions: TransactionToImport[] = [];

    for (const trnBlock of trnBlocks) {
      const trnContent = trnBlock.split(/<\/STMTTRN>/i)[0];

      const dateMatch = trnContent.match(/<DTPOSTED>(\d{8})/i);
      let date = '';
      if (dateMatch) {
        const raw = dateMatch[1];
        date = `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
      }

      const amtMatch = trnContent.match(/<TRNAMT>([\d.-]+)/i);
      let amount = 0;
      if (amtMatch) {
        const val = parseFloat(amtMatch[1]);
        amount = Math.round(val * 100);
      }

      const fitidMatch = trnContent.match(/<FITID>([^<\r\n]+)/i);
      const imported_id = fitidMatch ? fitidMatch[1].trim() : undefined;

      const nameMatch = trnContent.match(/<(?:NAME|PAYEE)>([^<\r\n]+)/i);
      const payee_name = nameMatch ? nameMatch[1].trim() : undefined;

      const memoMatch = trnContent.match(/<MEMO>([^<\r\n]+)/i);
      const notes = memoMatch ? memoMatch[1].trim() : undefined;

      if (date && !isNaN(amount)) {
        transactions.push({
          date,
          amount,
          payee_name,
          imported_id,
          notes
        });
      }
    }

    if (transactions.length > 0 || accountStatements.length === 0) {
      if (accountNumber) {
        const existing = accountStatements.find(s => s.accountNumber === accountNumber);
        if (existing) {
          existing.transactions.push(...transactions);
          continue;
        }
      }
      accountStatements.push({
        accountNumber,
        transactions
      });
    }
  }

  return {
    accountStatements
  };
}
