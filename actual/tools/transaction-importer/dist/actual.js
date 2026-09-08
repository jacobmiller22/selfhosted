import api from '@actual-app/api';
import fs from 'fs';
import path from 'path';
export async function connectActual(serverUrl, password, syncId, dataDir) {
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
export async function fetchAccounts() {
    const rawAccounts = await api.getAccounts();
    return (rawAccounts || []).map((acc) => ({
        id: acc.id,
        name: acc.name,
        type: acc.type,
        offbudget: !!acc.offbudget,
        closed: !!acc.closed
    }));
}
export async function importTransactionsToAccount(accountId, transactions) {
    const result = await api.importTransactions(accountId, transactions);
    return result || { added: [], updated: [] };
}
export async function disconnectActual() {
    await api.shutdown();
}
