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

console.log("\n🎉 All Re-annotation Unit Tests Passed!");
