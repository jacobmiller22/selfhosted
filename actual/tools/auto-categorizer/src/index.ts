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
const SYNC_ID = process.env.ACTUAL_SYNC_ID || "";
const CONFIDENCE_THRESHOLD = parseFloat(process.env.CONFIDENCE_THRESHOLD || "0.85");
const CRON_SCHEDULE = process.env.CRON_SCHEDULE || "*/15 * * * *"; // Every 15 minutes by default
const PORT = parseInt(process.env.PORT || "3080", 10);
const MODELS_DIR = process.env.MODELS_DIR || path.resolve(process.cwd(), "src/models");

const predictor = new OnnxPredictorEngine(MODELS_DIR);
let isSyncing = false;
let lastSyncTime: string | null = null;

async function runAutoCategorizerSync(): Promise<{ processed: number; transfersMatched: number; updated: number }> {
  if (isSyncing) {
    console.log("⚠️ Auto-categorization sync already in progress. Skipping cycle.");
    return { processed: 0, transfersMatched: 0, updated: 0 };
  }

  if (!SERVER_URL || !PASSWORD || !SYNC_ID) {
    console.error("❌ Actual server credentials missing (ACTUAL_SERVER_URL, ACTUAL_PASSWORD, ACTUAL_SYNC_ID).");
    return { processed: 0, transfersMatched: 0, updated: 0 };
  }

  isSyncing = true;
  console.log(`\n==================================================`);
  console.log(`🔄 Starting Auto-Categorization Sync Cycle at ${new Date().toISOString()}`);
  console.log(`==================================================`);

  let processedCount = 0;
  let transferCount = 0;
  let updatedCount = 0;

  try {
    await connectActual(SERVER_URL, PASSWORD, SYNC_ID);
    const transactions = await fetchAllTransactions();
    const payees = await fetchPayees();
    const categories = await fetchCategories();

    console.log(`📊 Fetched ${transactions.length} total transactions from Actual Budget.`);

    // --- STAGE 1: Transfer Detection ---
    console.log("\n🔍 Stage 1: Checking for cross-account transfers...");
    const transferPairs = findMatchingTransfers(transactions);
    console.log(`✓ Found ${transferPairs.length} matched transfer pairs.`);

    for (const pair of transferPairs) {
      if (!pair.txA.transfer_id && !pair.txB.transfer_id) {
        // Link transactions in Actual
        await updateTransaction(pair.txA.id, { transfer_id: pair.txB.id });
        await updateTransaction(pair.txB.id, { transfer_id: pair.txA.id });
        transferCount++;
        console.log(`  🔗 Linked Transfer: ${pair.txA.date} ($${(Math.abs(pair.txA.amount)/100).toFixed(2)}) across accounts.`);
      }
    }

    // --- STAGE 2 & 3: Uncategorized Payee & Category Auto-Classification ---
    console.log("\n🤖 Stage 2 & 3: Running ML Inference on Uncategorized Transactions...");
    const uncategorizedTxs = transactions.filter((t) => !t.category && !t.transfer_id);
    console.log(`📋 Found ${uncategorizedTxs.length} uncategorized transactions.`);

    for (const tx of uncategorizedTxs) {
      const rawPayee = tx.imported_payee || tx.payee || "";
      if (!rawPayee) continue;

      processedCount++;

      // Predict Payee
      const payeePred = await predictor.predictPayee(rawPayee, tx.account, tx.amount);
      // Predict Category
      const catPred = await predictor.predictCategory(rawPayee, tx.account, tx.amount, tx.date);

      const updates: { payee?: string; category?: string; notes?: string } = {};

      if (!tx.payee && payeePred.confidence >= CONFIDENCE_THRESHOLD) {
        updates.payee = payeePred.label;
      }

      if (catPred.confidence >= CONFIDENCE_THRESHOLD) {
        updates.category = catPred.label;
        console.log(`  ✅ [Auto-Assigned] "${rawPayee}" -> Category: ${catPred.label} (${(catPred.confidence * 100).toFixed(1)}%)`);
      } else {
        // High suggestion note if medium confidence
        const suggestedCat = categories.find((c) => c.id === catPred.label)?.name || catPred.label;
        updates.notes = `[ML Suggestion: ${suggestedCat} (${(catPred.confidence * 100).toFixed(0)}%)]`;
        console.log(`  💡 [Low Confidence Suggestion] "${rawPayee}" -> ${suggestedCat} (${(catPred.confidence * 100).toFixed(1)}%)`);
      }

      if (Object.keys(updates).length > 0) {
        await updateTransaction(tx.id, updates);
        updatedCount++;
      }
    }

    lastSyncTime = new Date().toISOString();
    console.log(`\n🎉 Sync finished! Updated ${updatedCount} transactions (${transferCount} transfers linked).`);
  } catch (err) {
    console.error("❌ Error during auto-categorizer sync cycle:", err);
  } finally {
    try {
      await disconnectActual();
    } catch (_) {}
    isSyncing = false;
  }

  return { processed: processedCount, transfersMatched: transferCount, updated: updatedCount };
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
    modelsDir: MODELS_DIR
  });
});

app.post("/api/sync", async (req, res) => {
  const result = await runAutoCategorizerSync();
  res.json({ status: "sync_completed", ...result });
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

  try {
    await predictor.init();
  } catch (err) {
    console.warn(`⚠️ Warning: ONNX predictor init error: ${(err as Error).message}. Daemon will wait for model upload.`);
  }

  // Start HTTP API
  app.listen(PORT, () => {
    console.log(`🚀 Sidecar HTTP server listening on port ${PORT}`);
    console.log(`   Health Check: GET http://localhost:${PORT}/health`);
    console.log(`   Manual Sync:  POST http://localhost:${PORT}/api/sync`);
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

startDaemon();
