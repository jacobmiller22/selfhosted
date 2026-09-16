import { Command } from "commander";
import fs from "fs";
import path from "path";
import {
  connectActual,
  disconnectActual,
  fetchAccounts,
  importTransactionsToAccount,
  type TransactionToImport,
} from "./actual.js";
import { getConfig, loadMappings } from "./config.js";
import { matchAccountFromIdentifier } from "./vision/accountMatcher.js";
import { generateTransactionFingerprint } from "./vision/deduplicator.js";

const program = new Command();

program
  .name("import-staged")
  .description("Bridge CLI for Antigravity /budget-upload skill to inspect accounts and import staged transactions into Actual Budget.");

program
  .command("list-accounts")
  .description("List all active Actual Budget accounts and mappings")
  .action(async () => {
    const config = getConfig();
    const mappings = loadMappings(config.mappingsPath);

    try {
      await connectActual(
        config.serverUrl,
        config.password || "",
        config.syncId,
        config.dataDir
      );
      const accounts = await fetchAccounts();
      await disconnectActual();

      const result = accounts
        .filter((a) => !a.closed)
        .map((a) => {
          // Find if there's an account number mapped in mappings.json
          const matchedNum = Object.entries(mappings.accountNumbers).find(
            ([, id]) => id === a.id
          )?.[0];
          return {
            id: a.id,
            name: a.name,
            type: a.type || "standard",
            mappedAccountNumber: matchedNum || null,
          };
        });

      console.log(JSON.stringify({ success: true, accounts: result, mappings }, null, 2));
    } catch (err: any) {
      console.error(
        JSON.stringify({
          success: false,
          error: err.message || String(err),
        })
      );
      process.exit(1);
    }
  });

program
  .command("commit")
  .description("Commit an array of staged transactions into Actual Budget")
  .option("-f, --file <jsonPath>", "Path to JSON file containing array of staged transactions")
  .option("-j, --json <rawJson>", "Raw JSON string of transactions")
  .option("-d, --dry-run", "Simulate import without modifying budget", false)
  .action(async (options: { file?: string; json?: string; dryRun: boolean }) => {
    let rawTransactions: any[] = [];

    if (options.file) {
      const filePath = path.resolve(options.file);
      if (!fs.existsSync(filePath)) {
        console.error(JSON.stringify({ success: false, error: `File not found: ${filePath}` }));
        process.exit(1);
      }
      rawTransactions = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    } else if (options.json) {
      rawTransactions = JSON.parse(options.json);
    } else {
      console.error(JSON.stringify({ success: false, error: "Either --file or --json must be provided." }));
      process.exit(1);
    }

    if (!Array.isArray(rawTransactions) || rawTransactions.length === 0) {
      console.log(JSON.stringify({ success: true, imported: 0, message: "No transactions to import." }));
      return;
    }

    const config = getConfig();
    const mappings = loadMappings(config.mappingsPath);

    try {
      await connectActual(
        config.serverUrl,
        config.password || "",
        config.syncId,
        config.dataDir
      );

      const accounts = await fetchAccounts();

      // Group transactions by account ID
      const groupedByAccount: Record<string, TransactionToImport[]> = {};

      for (const t of rawTransactions) {
        let accountId = t.account_id || t.accountId;

        // Auto-resolve account if missing
        if (!accountId) {
          const matched = matchAccountFromIdentifier(
            t.account_identifier || t.accountName,
            t.account_last_4,
            mappings,
            accounts
          );
          accountId = matched.accountId;
        }

        if (!accountId) {
          throw new Error(
            `Unable to resolve Actual Budget account for transaction: ${t.payee_name || t.payee} on ${t.date} ($${((t.amount || t.amount_cents) / 100).toFixed(2)}). Please specify an account_id.`
          );
        }

        const cents =
          typeof t.amount_cents === "number"
            ? t.amount_cents
            : typeof t.amount === "number"
            ? Math.round(t.amount * 100)
            : 0;

        const payeeName = (t.payee_name || t.payee || "Unknown Payee").trim();
        const date = t.date;
        const fingerprint =
          t.imported_id ||
          generateTransactionFingerprint({
            date,
            amount_cents: cents,
            payee: payeeName,
          });

        const txPayload: TransactionToImport = {
          account: accountId,
          date,
          amount: cents,
          payee_name: payeeName,
          imported_id: fingerprint,
          notes: t.notes || "",
          cleared: t.cleared !== undefined ? !!t.cleared : true,
        };

        if (!groupedByAccount[accountId]) {
          groupedByAccount[accountId] = [];
        }
        groupedByAccount[accountId].push(txPayload);
      }

      let totalAdded = 0;
      let totalUpdated = 0;
      const accountSummaries: Array<{ accountName: string; count: number; netCents: number }> = [];

      for (const [accId, txs] of Object.entries(groupedByAccount)) {
        const accObj = accounts.find((a) => a.id === accId);
        const accountName = accObj ? accObj.name : accId;
        const netCents = txs.reduce((sum, tx) => sum + tx.amount, 0);

        if (options.dryRun) {
          totalAdded += txs.length;
        } else {
          const res = await importTransactionsToAccount(accId, txs);
          totalAdded += (res.added || []).length;
          totalUpdated += (res.updated || []).length;
        }

        accountSummaries.push({
          accountName,
          count: txs.length,
          netCents,
        });
      }

      await disconnectActual();

      console.log(
        JSON.stringify(
          {
            success: true,
            dryRun: options.dryRun,
            totalStaged: rawTransactions.length,
            totalAdded,
            totalUpdated,
            accounts: accountSummaries,
          },
          null,
          2
        )
      );
    } catch (err: any) {
      await disconnectActual().catch(() => {});
      console.error(
        JSON.stringify({
          success: false,
          error: err.message || String(err),
        })
      );
      process.exit(1);
    }
  });

program
  .command("archive")
  .description("Move processed screenshots / statements into an archived/ subfolder")
  .argument("<filePaths...>", "Files to archive")
  .action((filePaths: string[]) => {
    const archived: string[] = [];

    for (const rawPath of filePaths) {
      const fullPath = path.resolve(rawPath);
      if (!fs.existsSync(fullPath)) continue;

      const dir = path.dirname(fullPath);
      const filename = path.basename(fullPath);
      const archiveDir = path.join(dir, "archived");

      if (!fs.existsSync(archiveDir)) {
        fs.mkdirSync(archiveDir, { recursive: true });
      }

      const destPath = path.join(archiveDir, filename);
      fs.renameSync(fullPath, destPath);
      archived.push(destPath);
    }

    console.log(JSON.stringify({ success: true, archived }));
  });

program.parse();
