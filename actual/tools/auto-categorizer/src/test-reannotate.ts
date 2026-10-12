import { appendRecommendationNote, isCategoryPersonaCompatible } from "./index.js";

function assert(condition: boolean, message: string) {
  if (!condition) {
    console.error(`❌ Assertion Failed: ${message}`);
    process.exit(1);
  }
}

console.log("--- Testing Re-annotation Helpers ---");

// Test 1: Empty note
const note1 = appendRecommendationNote("", "[ML Recommended Category: Groceries (90%)]");
assert(note1 === "[ML Recommended Category: Groceries (90%)]", `Note 1 failed: "${note1}"`);
console.log("✓ Empty note correctly populated");

// Test 2: User note without ML tag
const note2 = appendRecommendationNote("Trip to Lake Tahoe", "[ML Recommended Category: Vacation (95%)]");
assert(note2 === "Trip to Lake Tahoe [ML Recommended Category: Vacation (95%)]", `Note 2 failed: "${note2}"`);
console.log("✓ User custom note preserved when adding ML tag");

// Test 3: Existing ML tag replaced
const note3 = appendRecommendationNote(
  "Trip to Lake Tahoe [ML Suggested Category: General (40%)]",
  "[ML Recommended Category: Vacation (95%)]"
);
assert(note3 === "Trip to Lake Tahoe [ML Recommended Category: Vacation (95%)]", `Note 3 failed: "${note3}"`);
console.log("✓ Old ML suggestion tag replaced cleanly");

// Test 3b: Existing ML tag with persona brackets [P] or [J] replaced cleanly
const note3b = appendRecommendationNote(
  "[ML Suggested Category: Income [P] (20%)]",
  "[ML Recommended Category: Fun [P] (54%)]"
);
assert(note3b === "[ML Recommended Category: Fun [P] (54%)]", `Note 3b failed: "${note3b}"`);
const note3c = appendRecommendationNote(
  "User manual note [ML Suggested Category: Fun [J] (29%)]",
  "[ML Recommended Category: Common Fun (85%)]"
);
assert(note3c === "User manual note [ML Recommended Category: Common Fun (85%)]", `Note 3c failed: "${note3c}"`);
console.log("✓ Old ML tags with nested [P]/[J] brackets replaced without leaving trailing fragments");

// Test 3d: Scrubbing legacy orphaned percentage tags
const note3d = appendRecommendationNote(
  "7708: TN GA INST TECH PAYPAT  (92%)]  (92%)]  (92%)] [ML Recommended Category: Buffer Budget [J] (92%)]",
  "[ML Suggested Category: Buffer Budget [J] (37%)]"
);
assert(note3d === "7708: TN GA INST TECH PAYPAT [ML Suggested Category: Buffer Budget [J] (37%)]", `Note 3d failed: "${note3d}"`);
console.log("✓ Legacy orphaned percentage fragments scrubbed cleanly");

// Test 4: Existing transfer ML tag replaced
const note4 = appendRecommendationNote(
  "[ML Recommended Transfer: Matched with Checking $50.00 on 2026-09-01]",
  "[ML Recommended Category: Savings (99%)]"
);
assert(note4 === "[ML Recommended Category: Savings (99%)]", `Note 4 failed: "${note4}"`);
console.log("✓ Transfer ML tag replaced when re-annotated");

// Test 5: Persona compatibility check
assert(isCategoryPersonaCompatible("Fun [P]", "P") === true, "P persona should match [P]");
assert(isCategoryPersonaCompatible("Fun [J]", "P") === false, "P persona should reject [J]");
assert(isCategoryPersonaCompatible("Fun [P]", "J") === false, "J persona should reject [P]");
assert(isCategoryPersonaCompatible("Fun [J]", "J") === true, "J persona should match [J]");
assert(isCategoryPersonaCompatible("Groceries", "P") === true, "Joint category compatible with P");
assert(isCategoryPersonaCompatible("Groceries", "Joint") === true, "Joint category compatible with Joint");
console.log("✓ Persona compatibility checks verified");

// Test 6: Account persona extraction
import { getAccountPersona, resolveCategoryId } from "./index.js";
assert(getAccountPersona("360 Checking [P]") === "P", "360 Checking [P] must be P");
assert(getAccountPersona("Venture Card [P]") === "P", "Venture Card [P] must be P");
assert(getAccountPersona("Paige Personal Account") === "P", "Paige Personal Account must be P");
assert(getAccountPersona("360 Checking [J]") === "J", "360 Checking [J] must be J");
assert(getAccountPersona("Quicksilver Card [J]") === "J", "Quicksilver Card [J] must be J");
assert(getAccountPersona("Jacob Primary Account") === "J", "Jacob Primary Account must be J");
assert(getAccountPersona("Savings Joint") === "Joint", "Savings Joint must be Joint");
console.log("✓ Account persona extraction verified across P, J, and Joint accounts");

// Test 7: Strict persona enforcement in resolveCategoryId
const mockCategories = [
  { id: "cat_fun_j", name: "Fun [J]", hidden: false, tombstone: false },
  { id: "cat_fun_p", name: "Fun [P]", hidden: false, tombstone: false },
  { id: "cat_groc", name: "Groceries", hidden: false, tombstone: false }
];

// Incompatible top prediction must be bypassed for P account
const pPrediction = {
  label: "cat_fun_j",
  confidence: 0.95,
  probabilities: {
    cat_fun_j: 0.95,
    cat_fun_p: 0.04,
    cat_groc: 0.01
  }
};
const pResolved = resolveCategoryId(pPrediction, mockCategories, undefined, "P");
assert(pResolved === "cat_fun_p", `P persona must resolve to cat_fun_p, got: ${pResolved}`);
assert(pResolved !== "cat_fun_j", "P persona must NEVER resolve to cat_fun_j");

// Incompatible top prediction must be bypassed for J account
const jPrediction = {
  label: "cat_fun_p",
  confidence: 0.92,
  probabilities: {
    cat_fun_p: 0.92,
    cat_fun_j: 0.05,
    cat_groc: 0.03
  }
};
const jResolved = resolveCategoryId(jPrediction, mockCategories, undefined, "J");
assert(jResolved === "cat_fun_j", `J persona must resolve to cat_fun_j, got: ${jResolved}`);
assert(jResolved !== "cat_fun_p", "J persona must NEVER resolve to cat_fun_p");

// Direct string prediction incompatible with persona must return null or fallback, never incompatible category
const pDirectStringResolved = resolveCategoryId("cat_fun_j", mockCategories, undefined, "P");
assert(pDirectStringResolved !== "cat_fun_j", "Direct string cat_fun_j must never be returned for P persona");

console.log("✓ Strict persona enforcement in resolveCategoryId verified");

console.log("\n🎉 All Re-annotation Unit Tests Passed!");
