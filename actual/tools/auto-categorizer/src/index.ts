import express from "express";
import multer from "multer";
import cron from "node-cron";
import dotenv from "dotenv";
import path from "path";
import fs from "fs";

import {
  connectActual,
  disconnectActual,
  fetchAllTransactions,
  fetchAccounts,
  fetchPayees,
  fetchCategories,
  updateTransaction
} from "./actual.js";
import { OnnxPredictorEngine } from "./predictor.js";
import { findMatchingTransfers } from "./transfer.js";

dotenv.config();

let SERVER_URL = process.env.ACTUAL_SERVER_URL || "https://budget.cloud.jacobmiller22.com";
if (SERVER_URL.includes("actual_server")) {
  SERVER_URL = "https://budget.cloud.jacobmiller22.com";
}
const PASSWORD = process.env.ACTUAL_PASSWORD || "";
let SYNC_ID = process.env.ACTUAL_SYNC_ID || "d87856b0-5fd1-4b3e-85bc-bf1e9244d4be";
if (SYNC_ID === "a2bf28aa-7ae9-4948-837c-346f4e91d346" || !SYNC_ID) {
  SYNC_ID = "d87856b0-5fd1-4b3e-85bc-bf1e9244d4be";
}
const CONFIDENCE_THRESHOLD = parseFloat(process.env.CONFIDENCE_THRESHOLD || "0.85");
const BATCH_SIZE = parseInt(process.env.BATCH_SIZE || "50", 10);
const CRON_SCHEDULE = process.env.CRON_SCHEDULE || "*/15 * * * *"; // Every 15 minutes by default
const PORT = parseInt(process.env.PORT || "3080", 10);
const MODELS_DIR = process.env.MODELS_DIR || path.resolve(process.cwd(), "src/models");
const DEFAULT_DRY_RUN = process.env.DRY_RUN !== "false"; // Default to DRY RUN mode

const predictor = new OnnxPredictorEngine(MODELS_DIR);
let isSyncing = false;
let lastSyncTime: string | null = null;

export interface ProposedTransfer {
  txAId: string;
  txBId: string;
  date: string;
  amount: number;
  accountA: string;
  accountB: string;
  payeeA: string;
  payeeB: string;
}

export interface ProposedAssignment {
  txId: string;
  date: string;
  account: string;
  importedPayee: string;
  categoryName: string;
  confidence: number;
}

export interface ProposedSuggestion {
  txId: string;
  date: string;
  account: string;
  importedPayee: string;
  suggestedCategory: string;
  confidence: number;
}

export interface DryRunReport {
  timestamp: string;
  dryRun: boolean;
  totalTransactions: number;
  uncategorizedInBudgetAccounts: number;
  processed: number;
  transfersMatched: number;
  highConfidenceAssigned: number;
  lowConfidenceSuggested: number;
  proposedTransfers: ProposedTransfer[];
  proposedAssignments: ProposedAssignment[];
  proposedSuggestions: ProposedSuggestion[];
}

let latestReport: DryRunReport | null = null;

const REPORT_FILE_PATH = path.resolve(process.cwd(), ".latest-dry-run-report.json");
if (fs.existsSync(REPORT_FILE_PATH)) {
  try {
    latestReport = JSON.parse(fs.readFileSync(REPORT_FILE_PATH, "utf-8"));
  } catch (_) {}
}

function appendRecommendationNote(existingNotes: string | undefined | null, newRecommendation: string): string {
  const cleaned = (existingNotes || "")
    .replace(/\[ML (Recommended|Suggested|Transfer).*?\]/g, "")
    .trim();
  return cleaned ? `${cleaned} ${newRecommendation}` : newRecommendation;
}

function resolveCategoryId(predictedLabel: string, categories: { id: string; name: string; is_income?: boolean; hidden?: boolean }[]): string | null {
  const directMatch = categories.find((c) => c.id === predictedLabel);
  if (directMatch) return directMatch.id;

  const cleanLabel = predictedLabel.replace(/^cat_/, "").replace(/_/g, " ").toLowerCase();
  const nameMatch = categories.find((c) => c.name.toLowerCase() === cleanLabel && !c.hidden) || categories.find((c) => c.name.toLowerCase() === cleanLabel);
  if (nameMatch) return nameMatch.id;

  if (predictedLabel === "cat_income") {
    const incomeCat = categories.find((c) => c.is_income && !c.hidden) || categories.find((c) => c.is_income);
    if (incomeCat) return incomeCat.id;
  }
  if (predictedLabel === "cat_groceries") {
    const grocCat = categories.find((c) => c.name.toLowerCase().includes("grocer"));
    if (grocCat) return grocCat.id;
  }
  if (predictedLabel === "cat_subscriptions") {
    const subCat = categories.find((c) => c.name.toLowerCase().includes("subscript") && !c.hidden) || categories.find((c) => c.name.toLowerCase().includes("subscript"));
    if (subCat) return subCat.id;
  }
  if (predictedLabel === "cat_utilities" || predictedLabel === "cat_bills") {
    const utilCat = categories.find((c) => (c.name.toLowerCase().includes("bill") || c.name.toLowerCase().includes("util")) && !c.hidden);
    if (utilCat) return utilCat.id;
  }
  if (predictedLabel === "cat_dining") {
    const diningCat = categories.find((c) => (c.name.toLowerCase().includes("dining") || c.name.toLowerCase().includes("food")) && !c.hidden);
    if (diningCat) return diningCat.id;
  }
  return null;
}

export async function runAutoCategorizerSync(overrideDryRun?: boolean): Promise<DryRunReport> {
  const dryRun = overrideDryRun !== undefined ? overrideDryRun : DEFAULT_DRY_RUN;

  if (isSyncing) {
    console.log("⚠️ Auto-categorization sync already in progress. Skipping cycle.");
    return latestReport || {
      timestamp: new Date().toISOString(),
      dryRun,
      totalTransactions: 0,
      uncategorizedInBudgetAccounts: 0,
      processed: 0,
      transfersMatched: 0,
      highConfidenceAssigned: 0,
      lowConfidenceSuggested: 0,
      proposedTransfers: [],
      proposedAssignments: [],
      proposedSuggestions: []
    };
  }

  if (!SERVER_URL || !PASSWORD || !SYNC_ID) {
    console.error("❌ Actual server credentials missing (ACTUAL_SERVER_URL, ACTUAL_PASSWORD, ACTUAL_SYNC_ID).");
    throw new Error("Missing Actual server credentials");
  }

  isSyncing = true;
  console.log(`\n==================================================`);
  console.log(`🔄 Starting Auto-Categorization Sync Cycle at ${new Date().toISOString()}`);
  console.log(`🔒 Mode: ${dryRun ? "🧪 DRY-RUN (SIMULATION ONLY - NO MUTATIONS)" : "⚡ LIVE (MUTATIONS ENABLED)"}`);
  console.log(`==================================================`);

  const proposedTransfers: ProposedTransfer[] = [];
  const proposedAssignments: ProposedAssignment[] = [];
  const proposedSuggestions: ProposedSuggestion[] = [];

  let processedCount = 0;
  let transferCount = 0;

  try {
    await connectActual(SERVER_URL, PASSWORD, SYNC_ID);
    const transactions = await fetchAllTransactions();
    const accounts = await fetchAccounts();
    const acctMap = new Map(accounts.map((a) => [a.id, a]));
    const payees = await fetchPayees();
    const categories = await fetchCategories();

    console.log(`📊 Fetched ${transactions.length} total transactions across ${accounts.length} accounts from Actual Budget.`);

    // --- STAGE 1: Transfer Detection ---
    console.log("\n🔍 Stage 1: Checking for cross-account transfers in open, on-budget accounts...");
    const openOnBudgetTxs = transactions.filter((t) => {
      if (t.is_parent || t.is_child) return false;
      const acct = acctMap.get(t.account);
      if (!acct || acct.closed || acct.offbudget) return false;
      return true;
    });
    const transferPairs = findMatchingTransfers(openOnBudgetTxs);
    console.log(`✓ Found ${transferPairs.length} matched transfer pairs.`);

    for (const pair of transferPairs) {
      if (!pair.txA.transfer_id && !pair.txB.transfer_id) {
        const acctAName = acctMap.get(pair.txA.account)?.name || pair.txA.account;
        const acctBName = acctMap.get(pair.txB.account)?.name || pair.txB.account;
        const payeeAName = pair.txA.imported_payee || pair.txA.payee || "(transfer)";
        const payeeBName = pair.txB.imported_payee || pair.txB.payee || "(transfer)";

        proposedTransfers.push({
          txAId: pair.txA.id,
          txBId: pair.txB.id,
          date: pair.txA.date,
          amount: Math.abs(pair.txA.amount) / 100,
          accountA: acctAName,
          accountB: acctBName,
          payeeA: payeeAName,
          payeeB: payeeBName
        });

        transferCount++;

        if (dryRun) {
          const noteA = appendRecommendationNote(pair.txA.notes, `[ML Recommended Transfer: Matched with ${acctBName} $${(Math.abs(pair.txA.amount)/100).toFixed(2)} on ${pair.txB.date}]`);
          const noteB = appendRecommendationNote(pair.txB.notes, `[ML Recommended Transfer: Matched with ${acctAName} $${(Math.abs(pair.txB.amount)/100).toFixed(2)} on ${pair.txA.date}]`);
          await updateTransaction(pair.txA.id, { notes: noteA, account: pair.txA.account });
          await updateTransaction(pair.txB.id, { notes: noteB, account: pair.txB.account });
          console.log(`  🧪 [DRY-RUN NOTES UPDATED] Recommended Transfer: ${pair.txA.date} ($${(Math.abs(pair.txA.amount)/100).toFixed(2)}) between [${acctAName}] and [${acctBName}]`);
        } else {
          await updateTransaction(pair.txA.id, { transfer_id: pair.txB.id, account: pair.txA.account, category: null });
          await updateTransaction(pair.txB.id, { transfer_id: pair.txA.id, account: pair.txB.account, category: null });
          console.log(`  🔗 [LIVE LINKED] Transfer: ${pair.txA.date} ($${(Math.abs(pair.txA.amount)/100).toFixed(2)}) across accounts.`);
        }
      }
    }

    // --- STAGE 2 & 3: Uncategorized Payee & Category Auto-Classification ---
    console.log("\n🤖 Stage 2 & 3: Running ML Inference on Uncategorized Transactions...");
    try {
      await predictor.init();
    } catch (err) {
      console.warn(`⚠️ Warning initializing predictor sessions: ${(err as Error).message}`);
    }

    // Only process transactions belonging to open, on-budget accounts
    const allUncategorized = transactions.filter((t) => {
      const acct = acctMap.get(t.account);
      if (!acct || acct.closed || acct.offbudget) return false;
      return !t.category && !t.transfer_id && !t.is_parent && !t.is_child;
    });
    const uncategorizedTxs = allUncategorized.slice(0, BATCH_SIZE);
    console.log(`📋 Found ${allUncategorized.length} uncategorized transactions in open, on-budget accounts. Processing batch of ${uncategorizedTxs.length}.`);

    for (const tx of uncategorizedTxs) {
      const rawPayee = tx.imported_payee || tx.payee || "";
      if (!rawPayee) continue;

      processedCount++;
      const acctName = acctMap.get(tx.account)?.name || tx.account;

      // Predict Payee
      const payeePred = await predictor.predictPayee(rawPayee, tx.account, tx.amount);
      // Predict Category
      const catPred = await predictor.predictCategory(rawPayee, tx.account, tx.amount, tx.date);

      const updates: { payee?: string; category?: string; notes?: string; account?: string } = {};

      if (!tx.payee && payeePred.confidence >= CONFIDENCE_THRESHOLD) {
        updates.payee = payeePred.label;
      }

      const resolvedCatId = resolveCategoryId(catPred.label, categories);
      const catName = categories.find((c) => c.id === resolvedCatId)?.name || catPred.label;

      if (catPred.confidence >= CONFIDENCE_THRESHOLD && resolvedCatId) {
        updates.category = resolvedCatId;
        proposedAssignments.push({
          txId: tx.id,
          date: tx.date,
          account: acctName,
          importedPayee: rawPayee,
          categoryName: catName,
          confidence: parseFloat((catPred.confidence * 100).toFixed(1))
        });

        if (dryRun) {
          const recNote = appendRecommendationNote(tx.notes, `[ML Recommended Category: ${catName} (${(catPred.confidence * 100).toFixed(0)}%)]`);
          await updateTransaction(tx.id, { notes: recNote, account: tx.account });
          console.log(`  🧪 [DRY-RUN NOTES UPDATED] "${rawPayee}" -> Recommended Category: ${catName} (${(catPred.confidence * 100).toFixed(1)}%)`);
        } else {
          console.log(`  ✅ [LIVE AUTO-ASSIGNED] "${rawPayee}" -> Category: ${catName} (${(catPred.confidence * 100).toFixed(1)}%)`);
        }
      } else {
        updates.notes = `[ML Suggested Category: ${catName} (${(catPred.confidence * 100).toFixed(0)}%)]`;
        proposedSuggestions.push({
          txId: tx.id,
          date: tx.date,
          account: acctName,
          importedPayee: rawPayee,
          suggestedCategory: catName,
          confidence: parseFloat((catPred.confidence * 100).toFixed(1))
        });

        if (dryRun) {
          const recNote = appendRecommendationNote(tx.notes, `[ML Suggested Category: ${catName} (${(catPred.confidence * 100).toFixed(0)}%)]`);
          await updateTransaction(tx.id, { notes: recNote, account: tx.account });
          console.log(`  💡 [DRY-RUN NOTES UPDATED] "${rawPayee}" -> Suggested Category: ${catName} (${(catPred.confidence * 100).toFixed(1)}%)`);
        } else {
          console.log(`  💡 [LIVE SUGGESTION NOTE] "${rawPayee}" -> ${catName} (${(catPred.confidence * 100).toFixed(1)}%)`);
        }
      }

      if (!dryRun && Object.keys(updates).length > 0) {
        updates.account = tx.account;
        await updateTransaction(tx.id, updates);
      }
    }

    lastSyncTime = new Date().toISOString();
    latestReport = {
      timestamp: lastSyncTime,
      dryRun,
      totalTransactions: transactions.length,
      uncategorizedInBudgetAccounts: allUncategorized.length,
      processed: processedCount,
      transfersMatched: transferCount,
      highConfidenceAssigned: proposedAssignments.length,
      lowConfidenceSuggested: proposedSuggestions.length,
      proposedTransfers,
      proposedAssignments,
      proposedSuggestions
    };

    fs.writeFileSync(REPORT_FILE_PATH, JSON.stringify(latestReport, null, 2), "utf-8");

    console.log(`\n🎉 Sync finished! ${dryRun ? "[DRY-RUN SIMULATED]" : "[LIVE COMPLETED]"}`);
    console.log(`   Transfers Matched: ${transferCount}`);
    console.log(`   High-Confidence Auto-Assignments: ${proposedAssignments.length}`);
    console.log(`   Low-Confidence Notes/Suggestions: ${proposedSuggestions.length}`);
  } catch (err) {
    console.error("❌ Error during auto-categorizer sync cycle:", err);
  } finally {
    try {
      await disconnectActual();
    } catch (_) {}
    isSyncing = false;
  }

  return latestReport || {
    timestamp: new Date().toISOString(),
    dryRun,
    totalTransactions: 0,
    uncategorizedInBudgetAccounts: 0,
    processed: processedCount,
    transfersMatched: transferCount,
    highConfidenceAssigned: proposedAssignments.length,
    lowConfidenceSuggested: proposedSuggestions.length,
    proposedTransfers,
    proposedAssignments,
    proposedSuggestions
  };
}

// --- EXPRESS HTTP SERVER (Health & Model Upload Endpoint) ---
const app = express();
app.use(express.json());

const upload = multer({ dest: path.resolve(process.cwd(), ".tmp-uploads") });

app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    isSyncing,
    lastSyncTime,
    dryRunModeDefault: DEFAULT_DRY_RUN,
    modelsDir: MODELS_DIR,
    lastReportSummary: latestReport
      ? {
          timestamp: latestReport.timestamp,
          dryRun: latestReport.dryRun,
          uncategorizedInBudgetAccounts: latestReport.uncategorizedInBudgetAccounts,
          transfersMatched: latestReport.transfersMatched,
          highConfidenceAssigned: latestReport.highConfidenceAssigned,
          lowConfidenceSuggested: latestReport.lowConfidenceSuggested
        }
      : null
  });
});

app.get("/api/reports/latest", (req, res) => {
  if (!latestReport) {
    return res.status(404).json({ error: "No dry-run report available yet. Run /api/sync first." });
  }
  res.json(latestReport);
});

app.post("/api/sync", async (req, res) => {
  const overrideDryRun = req.body && typeof req.body.dryRun === "boolean" ? req.body.dryRun : undefined;
  const report = await runAutoCategorizerSync(overrideDryRun);
  res.json({ status: "sync_completed", report });
});

app.post(
  "/api/models/upload",
  upload.fields([
    { name: "manifest", maxCount: 1 },
    { name: "payee_resolver", maxCount: 1 },
    { name: "category_classifier", maxCount: 1 }
  ]),
  async (req, res) => {
    try {
      const files = req.files as { [fieldname: string]: Express.Multer.File[] };
      if (!files.manifest || !files.payee_resolver || !files.category_classifier) {
        return res.status(400).json({ error: "Missing required model files (manifest, payee_resolver, category_classifier)" });
      }

      if (!fs.existsSync(MODELS_DIR)) {
        fs.mkdirSync(MODELS_DIR, { recursive: true });
      }

      fs.copyFileSync(files.manifest[0].path, path.join(MODELS_DIR, "model_manifest.json"));
      fs.copyFileSync(files.payee_resolver[0].path, path.join(MODELS_DIR, "payee_resolver.onnx"));
      fs.copyFileSync(files.category_classifier[0].path, path.join(MODELS_DIR, "category_classifier.onnx"));

      // Cleanup tmp files
      Object.values(files).flatMap((f) => f).forEach((file) => fs.unlinkSync(file.path));

      // Reload ONNX predictor sessions
      await predictor.init();

      console.log(`✓ Uploaded and reloaded ONNX models via REST API`);
      res.json({ status: "models_updated", timestamp: new Date().toISOString() });
    } catch (err: any) {
      console.error("❌ Failed to process model upload:", err);
      res.status(500).json({ error: err.message });
    }
  }
);

// --- DAEMON STARTUP ---
async function startDaemon() {
  console.log("Starting Actual Budget Auto-Categorizer Sidecar Daemon...");
  console.log(`⚙️ Default Mode: ${DEFAULT_DRY_RUN ? "🧪 DRY-RUN (DEFAULT)" : "⚡ LIVE"}`);

  try {
    await predictor.init();
  } catch (err) {
    console.warn(`⚠️ Warning: ONNX predictor init error: ${(err as Error).message}. Daemon will wait for model upload.`);
  }

  // Start HTTP API
  app.listen(PORT, () => {
    console.log(`🚀 Sidecar HTTP server listening on port ${PORT}`);
    console.log(`   Health Check:   GET http://localhost:${PORT}/health`);
    console.log(`   Latest Report:  GET http://localhost:${PORT}/api/reports/latest`);
    console.log(`   Manual Sync:    POST http://localhost:${PORT}/api/sync (body: {"dryRun": true})`);
  });

  // Schedule Cron Sync Loop
  if (cron.validate(CRON_SCHEDULE)) {
    console.log(`⏰ Scheduled periodic sync loop with cron expression: "${CRON_SCHEDULE}"`);
    cron.schedule(CRON_SCHEDULE, () => {
      runAutoCategorizerSync();
    });
  } else {
    console.warn(`⚠️ Invalid cron expression "${CRON_SCHEDULE}". Periodic scheduler disabled.`);
  }
}

if (process.env.AUTO_START !== "false") {
  startDaemon();
}
