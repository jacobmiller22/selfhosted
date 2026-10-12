import path from "path";
import { OnnxPredictorEngine } from "./predictor.js";

async function runTest() {
  console.log("--- Testing TS OnnxPredictorEngine ---");
  const modelsDir = path.resolve(process.cwd(), "src/models");
  const engine = new OnnxPredictorEngine(modelsDir);

  await engine.init();

  // Test Payee Prediction
  const payeeRes = await engine.predictPayee(
    "SQ *TRADER JOE'S #521 SAN FRANCISCO CA",
    "acct_credit_card",
    6500
  );
  console.log(`\nSample Input: "SQ *TRADER JOE'S #521 SAN FRANCISCO CA" ($65.00)`);
  console.log(`  Predicted Payee ID: "${payeeRes.label}"`);
  console.log(`  Confidence:         ${(payeeRes.confidence * 100).toFixed(1)}%`);

  // Test Category Prediction (Joint Persona)
  const catRes = await engine.predictCategory(
    "SQ *STARBUCKS COFFEE #08492",
    "acct_credit_card",
    550,
    "2026-09-08",
    "Joint"
  );
  console.log(`\nSample Input (Joint): "SQ *STARBUCKS COFFEE #08492" ($5.50)`);
  console.log(`  Predicted Category ID: "${catRes.label}"`);
  console.log(`  Confidence:            ${(catRes.confidence * 100).toFixed(1)}%`);

  // Test Category Prediction (Persona P)
  console.log("\n--- Testing Persona Isolation (TypeScript OnnxPredictorEngine) ---");
  const manifest = engine.getManifest()!;
  const catPersonas = manifest.models.category_classifier.category_personas || {};
  const pCatIds = new Set(Object.entries(catPersonas).filter(([_, p]) => p === "P").map(([id]) => id));
  const jCatIds = new Set(Object.entries(catPersonas).filter(([_, p]) => p === "J").map(([id]) => id));

  if (pCatIds.size === 0 || jCatIds.size === 0) {
    throw new Error("Model manifest missing P or J category personas");
  }
  console.log(`✓ Manifest verified with ${pCatIds.size} P categories and ${jCatIds.size} J categories`);

  // Persona P Test
  const catResP = await engine.predictCategory(
    "SQ *STARBUCKS COFFEE #08492",
    "fe4ea4eb-c181-427d-8614-9d5ae736b613", // 360 Checking [P]
    550,
    "2026-09-08",
    "P"
  );
  if (jCatIds.has(catResP.label)) {
    throw new Error(`Violation: Persona P predicted J category: ${catResP.label}`);
  }
  for (const jCat of jCatIds) {
    if (catResP.probabilities[jCat] !== 0) {
      throw new Error(`Violation: Persona P has non-zero probability for J category ${jCat}: ${catResP.probabilities[jCat]}`);
    }
  }
  console.log(`✓ Persona P correctly excluded from all J categories (selected: ${catResP.label})`);

  // Persona J Test
  const catResJ = await engine.predictCategory(
    "SQ *STARBUCKS COFFEE #08492",
    "6fd7b088-005e-4254-9d3c-3eb231a3f66c", // 360 Checking [J]
    550,
    "2026-09-08",
    "J"
  );
  if (pCatIds.has(catResJ.label)) {
    throw new Error(`Violation: Persona J predicted P category: ${catResJ.label}`);
  }
  for (const pCat of pCatIds) {
    if (catResJ.probabilities[pCat] !== 0) {
      throw new Error(`Violation: Persona J has non-zero probability for P category ${pCat}: ${catResJ.probabilities[pCat]}`);
    }
  }
  console.log(`✓ Persona J correctly excluded from all P categories (selected: ${catResJ.label})`);

  console.log("\n🎉 TypeScript ONNX Predictor Test Completed Successfully!");
}

runTest().catch((err) => {
  console.error("❌ Test failed:", err);
  process.exit(1);
});
