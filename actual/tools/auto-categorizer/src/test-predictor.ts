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

  // Test Category Prediction
  const catRes = await engine.predictCategory(
    "SQ *STARBUCKS COFFEE #08492",
    "acct_credit_card",
    550,
    "2026-09-08"
  );
  console.log(`\nSample Input: "SQ *STARBUCKS COFFEE #08492" ($5.50)`);
  console.log(`  Predicted Category ID: "${catRes.label}"`);
  console.log(`  Confidence:            ${(catRes.confidence * 100).toFixed(1)}%`);

  console.log("\n🎉 TypeScript ONNX Predictor Test Completed Successfully!");
}

runTest().catch((err) => {
  console.error("❌ Test failed:", err);
  process.exit(1);
});
