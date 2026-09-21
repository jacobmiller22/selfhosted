import dotenv from "dotenv";
import { runReannotation, ReannotationOptions } from "./index.js";

dotenv.config();

async function main() {
  const args = process.argv.slice(2);
  const options: ReannotationOptions = {
    dryRun: true
  };

  for (const arg of args) {
    if (arg === "--live" || arg === "--dry-run=false" || arg === "--dryRun=false") {
      options.dryRun = false;
    } else if (arg.startsWith("--limit=")) {
      options.limit = parseInt(arg.split("=")[1], 10);
    } else if (arg.startsWith("--since=")) {
      options.sinceDate = arg.split("=")[1];
    } else if (arg.startsWith("--account=")) {
      options.account = arg.split("=")[1];
    } else if (arg === "--include-all") {
      options.includeClosedOrOffbudget = true;
    }
  }

  try {
    const report = await runReannotation(options);
    console.log("\nRe-annotation Results:");
    console.log(JSON.stringify({
      dryRun: report.dryRun,
      totalScanned: report.totalTransactionsScanned,
      eligible: report.eligibleTransactions,
      notesUpdated: report.notesUpdated,
      notesUnchanged: report.notesUnchanged,
      skippedTransfers: report.skippedTransfers,
      skippedNoPayee: report.skippedNoPayee,
      duration: `${(report.durationMs / 1000).toFixed(1)}s`
    }, null, 2));

    if (report.samples.length > 0) {
      console.log(`\nSample ${Math.min(5, report.samples.length)} Changes:`);
      for (const s of report.samples.slice(0, 5)) {
        console.log(`- [${s.date}] ${s.payee} (${s.account})`);
        console.log(`  Existing Category: ${s.existingCategory || "(none)"}`);
        console.log(`  ML Suggestion:     ${s.predictedCategory} (${s.confidence}%)`);
        console.log(`  Old Note: "${s.oldNotes}"`);
        console.log(`  New Note: "${s.newNotes}"`);
      }
    }
    process.exit(0);
  } catch (err) {
    console.error("❌ Re-annotation failed:", err);
    process.exit(1);
  }
}

main();
