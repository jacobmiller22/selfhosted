import api from '@actual-app/api';
import fs from 'fs';
import path from 'path';

export interface ActualAccount {
  id: string;
  name: string;
  type?: string;
  offbudget?: boolean;
  closed?: boolean;
}

export interface ActualPayee {
  id: string;
  name: string;
  transfer_acct?: string;
}

export interface TransactionToImport {
  date: string;
  amount: number; // in cents
  payee?: string; // Payee ID in Actual Budget (e.g. transfer payee ID)
  payee_name?: string;
  imported_id?: string;
  notes?: string;
  cleared?: boolean;
}

export async function connectActual(
  serverUrl: string,
  password: string,
  syncId: string,
  dataDir?: string
): Promise<void> {
  const cacheDir = dataDir || path.resolve(process.cwd(), '.actual-cache');
  if (!fs.existsSync(cacheDir)) {
    fs.mkdirSync(cacheDir, { recursive: true });
  }

  await api.init({
    dataDir: cacheDir,
    serverURL: serverUrl,
    password: password
  });

  await api.downloadBudget(syncId);
}

export async function fetchAccounts(): Promise<ActualAccount[]> {
  const rawAccounts = await api.getAccounts();
  return (rawAccounts || []).map((acc: any) => ({
    id: acc.id,
    name: acc.name,
    type: acc.type,
    offbudget: !!acc.offbudget,
    closed: !!acc.closed
  }));
}

export async function fetchPayees(): Promise<ActualPayee[]> {
  const payees = await api.getPayees();
  return (payees || []).map((p: any) => ({
    id: p.id,
    name: p.name,
    transfer_acct: p.transfer_acct
  }));
}

export async function fetchAccountBalance(accountId: string): Promise<number> {
  const balance = await api.getAccountBalance(accountId);
  return typeof balance === 'number' ? balance : 0;
}

export async function importTransactionsToAccount(
  accountId: string,
  transactions: TransactionToImport[]
): Promise<{ added: any[]; updated: any[] }> {
  const result = await api.importTransactions(accountId, transactions);
  return result || { added: [], updated: [] };
}

export async function disconnectActual(): Promise<void> {
  await api.shutdown();
}
