import { parse } from 'csv-parse/sync';
import { TransactionToImport } from '../actual.js';
import type { AccountStatement, ParsedStatement } from './ofx.js';
import type { CsvProfile } from '../config.js';

export function parseCsvContent(
  content: string,
  filename?: string,
  profile?: CsvProfile
): ParsedStatement {
  const records = parse(content, {
    columns: true,
    skip_empty_lines: true,
    trim: true,
    relax_column_count: true
  });

  if (!records || records.length === 0) {
    return { accountStatements: [{ transactions: [] }] };
  }

  let accountNumber: string | undefined;
  const transactions: TransactionToImport[] = [];

  const rawHeaders: string[] = Object.keys(records[0]);

  const findHeader = (patterns: RegExp[]): string | undefined => {
    return rawHeaders.find(h => patterns.some(p => p.test(h.trim())));
  };

  const getHeader = (profileHeader?: string, patterns?: RegExp[]): string | undefined => {
    if (profileHeader !== undefined) {
      if (profileHeader === '' || profileHeader === '(None)') return undefined;
      return rawHeaders.find(h => h.trim() === profileHeader.trim()) || profileHeader;
    }
    return patterns ? findHeader(patterns) : undefined;
  };

  const dateHeader = getHeader(profile?.dateHeader, [/date/i, /posting date/i, /trans date/i, /transaction date/i]);
  const payeeHeader = getHeader(profile?.payeeHeader, [/payee/i, /description/i, /name/i, /merchant/i, /transaction description/i]);
  const amountHeader = getHeader(profile?.amountHeader, [/^amount$/i, /total/i, /transaction amount/i]);
  const outflowHeader = getHeader(profile?.outflowHeader, [/outflow/i, /debit/i, /payment/i, /payment amount/i, /withdrawal/i, /charge/i, /expense/i]);
  const inflowHeader = getHeader(profile?.inflowHeader, [/inflow/i, /credit/i, /deposit/i, /deposit amount/i, /income/i, /refund/i]);
  const typeHeader = getHeader(profile?.typeHeader, [/type/i, /transaction type/i, /trans type/i, /entry type/i]);
  const notesHeader = getHeader(profile?.notesHeader, [/memo/i, /notes/i, /category/i]);
  const acctHeader = getHeader(profile?.acctHeader, [/account/i, /acct/i, /account number/i]);
  const idHeader = getHeader(profile?.idHeader, [/id/i, /transaction id/i, /fitid/i, /reference/i]);

  const detectedHeaders: CsvProfile = {
    dateHeader,
    payeeHeader,
    amountHeader,
    outflowHeader,
    inflowHeader,
    typeHeader,
    notesHeader,
    acctHeader,
    idHeader
  };

  const hasDualColumns = (outflowHeader !== undefined || inflowHeader !== undefined) &&
    !(profile?.amountHeader && !profile?.outflowHeader && !profile?.inflowHeader);

  for (let index = 0; index < records.length; index++) {
    const row = records[index];

    if (!accountNumber && acctHeader && row[acctHeader]) {
      accountNumber = String(row[acctHeader]).trim();
    }

    let dateStr = dateHeader ? row[dateHeader] : '';
    let parsedDate = parseDateString(dateStr);

    if (!parsedDate) continue;

    let amount = 0;
    if (hasDualColumns) {
      let outflow = 0;
      let inflow = 0;
      if (outflowHeader && row[outflowHeader] !== undefined && row[outflowHeader] !== null && String(row[outflowHeader]).trim() !== '') {
        const raw = String(row[outflowHeader]).replace(/[$,]/g, '').trim();
        const val = parseFloat(raw);
        if (!isNaN(val)) outflow = Math.abs(val);
      }
      if (inflowHeader && row[inflowHeader] !== undefined && row[inflowHeader] !== null && String(row[inflowHeader]).trim() !== '') {
        const raw = String(row[inflowHeader]).replace(/[$,]/g, '').trim();
        const val = parseFloat(raw);
        if (!isNaN(val)) inflow = Math.abs(val);
      }
      amount = Math.round((inflow - outflow) * 100);
    } else if (amountHeader && row[amountHeader] !== undefined && row[amountHeader] !== null && String(row[amountHeader]).trim() !== '') {
      amount = parseAmountValue(String(row[amountHeader]));
      if (typeHeader && row[typeHeader] !== undefined && row[typeHeader] !== null && String(row[typeHeader]).trim() !== '') {
        const typeVal = String(row[typeHeader]).trim();
        const debitPatterns = [/debit/i, /payment/i, /withdrawal/i, /charge/i, /expense/i, /outflow/i, /purchase/i, /fee/i, /sale/i];
        const creditPatterns = [/credit/i, /deposit/i, /income/i, /refund/i, /inflow/i];
        if (debitPatterns.some(p => p.test(typeVal))) {
          amount = -Math.abs(amount);
        } else if (creditPatterns.some(p => p.test(typeVal))) {
          amount = Math.abs(amount);
        }
      }
    } else {
      let outflow = 0;
      let inflow = 0;
      if (outflowHeader && row[outflowHeader]) {
        const raw = String(row[outflowHeader]).replace(/[$,]/g, '').trim();
        const val = parseFloat(raw);
        if (!isNaN(val)) outflow = Math.abs(val);
      }
      if (inflowHeader && row[inflowHeader]) {
        const raw = String(row[inflowHeader]).replace(/[$,]/g, '').trim();
        const val = parseFloat(raw);
        if (!isNaN(val)) inflow = Math.abs(val);
      }
      amount = Math.round((inflow - outflow) * 100);
    }

    const payee_name = payeeHeader ? row[payeeHeader] : undefined;
    const notes = notesHeader ? row[notesHeader] : undefined;
    const imported_id = idHeader ? String(row[idHeader]) : `${parsedDate}-${index}-${amount}`;

    transactions.push({
      date: parsedDate,
      amount,
      payee_name,
      notes,
      imported_id
    });
  }

  return {
    accountStatements: [
      {
        accountNumber,
        transactions,
        detectedHeaders,
        csvHeaders: rawHeaders
      }
    ]
  };
}

function parseAmountValue(rawStr: string): number {
  if (!rawStr) return 0;
  let str = rawStr.trim().replace(/[$,]/g, '');
  let isNegative = false;
  if (str.startsWith('(') && str.endsWith(')')) {
    isNegative = true;
    str = str.slice(1, -1).trim();
  }
  const val = parseFloat(str);
  if (isNaN(val)) return 0;
  return Math.round((isNegative ? -Math.abs(val) : val) * 100);
}

function parseDateString(str: string): string | undefined {
  if (!str) return undefined;
  if (/^\d{4}-\d{2}-\d{2}$/.test(str)) {
    return str;
  }
  const m1 = str.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (m1) {
    const month = m1[1].padStart(2, '0');
    const day = m1[2].padStart(2, '0');
    const year = m1[3];
    return `${year}-${month}-${day}`;
  }
  if (/^\d{8}$/.test(str)) {
    return `${str.slice(0, 4)}-${str.slice(4, 6)}-${str.slice(6, 8)}`;
  }
  const d = new Date(str);
  if (!isNaN(d.getTime())) {
    return d.toISOString().split('T')[0];
  }
  return undefined;
}
