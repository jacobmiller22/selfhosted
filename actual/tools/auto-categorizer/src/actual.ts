import api from "@actual-app/api";
import fs from "fs";
import path from "path";
import { ActualTransaction } from "./transfer.js";

export interface ActualAccount {
  id: string;
  name: string;
  type?: string;
  closed?: boolean;
}

export interface ActualPayee {
  id: string;
  name: string;
  category?: string;
  transfer_acct?: string;
}

export interface ActualCategory {
  id: string;
  name: string;
  is_income?: boolean;
  tombstone?: boolean;
}

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

  await api.downloadBudget(syncId, { password });
  console.log(`✓ Connected to Actual Server: ${serverUrl} (Sync ID: ${syncId})`);
}

export async function fetchAccounts(): Promise<ActualAccount[]> {
  const accounts = await api.getAccounts();
  return (accounts || []).map((a: any) => ({
    id: a.id,
    name: a.name,
    type: a.type,
    closed: !!a.closed
  }));
}

export async function fetchPayees(): Promise<ActualPayee[]> {
  const payees = await api.getPayees();
  return (payees || []).map((p: any) => ({
    id: p.id,
    name: p.name,
    category: p.category,
    transfer_acct: p.transfer_acct
  }));
}

export async function fetchCategories(): Promise<ActualCategory[]> {
  const categories = await api.getCategories();
  return (categories || []).map((c: any) => ({
    id: c.id,
    name: c.name,
    is_income: !!c.is_income,
    tombstone: !!c.tombstone
  }));
}

export async function fetchAllTransactions(sinceDate?: string): Promise<ActualTransaction[]> {
  // Fetch transactions from Actual Budget
  const txs = await api.getTransactions(undefined, sinceDate, undefined);
  return (txs || []).map((t: any) => ({
    id: t.id,
    account: t.account,
    date: t.date,
    amount: t.amount,
    payee: t.payee,
    category: t.category,
    imported_payee: t.imported_payee || t.payee_name || "",
    transferred_id: t.transferred_id,
    cleared: !!t.cleared
  }));
}

export async function updateTransaction(
  id: string,
  updates: { payee?: string; category?: string; notes?: string }
): Promise<void> {
  await api.updateTransaction(id, updates);
}

export async function disconnectActual(): Promise<void> {
  await api.shutdown();
  console.log("✓ Disconnected from Actual API");
}
