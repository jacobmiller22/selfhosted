import assert from "assert";
import { buildHiddenToActiveMap, resolveCategoryId, CategoryInput } from "./index.js";

function runTests() {
  console.log("--- Testing Hidden-to-Active Category Resolver ---");

  const categories: CategoryInput[] = [
    { id: "cat_groceries_active", name: "Groceries & Supermarkets", hidden: false },
    { id: "cat_groceries_old", name: "Groceries (Deprecated)", hidden: true },
    { id: "cat_dining_active", name: "Restaurants & Dining", hidden: false },
    { id: "cat_dining_old", name: "Dining Out (Old)", hidden: true },
    { id: "cat_subs_active", name: "Subscriptions & Services", hidden: false },
    { id: "cat_subs_old", name: "Subscriptions (Old)", hidden: true },
  ];

  // 1. Test buildHiddenToActiveMap with time-weighted transactions
  const mockTransactions = [
    // Historical transactions under old dining category for Starbucks
    { date: "2025-01-10", imported_payee: "STARBUCKS #1024", category: "cat_dining_old" },
    { date: "2025-02-15", imported_payee: "STARBUCKS #1024", category: "cat_dining_old" },
    // Recent transactions under new dining category for Starbucks
    { date: "2026-08-01", imported_payee: "STARBUCKS #1024", category: "cat_dining_active" },
    { date: "2026-09-01", imported_payee: "STARBUCKS #1024", category: "cat_dining_active" },
  ];

  const hiddenMap = buildHiddenToActiveMap(mockTransactions, categories);
  console.log("✓ Computed runtime hidden-to-active map:", Array.from(hiddenMap.entries()));

  assert.strictEqual(
    hiddenMap.get("cat_dining_old"),
    "cat_dining_active",
    "cat_dining_old should map to cat_dining_active"
  );

  // 2. Test resolveCategoryId scenarios

  // Scenario A: Top prediction is already an ACTIVE category
  const resActive = resolveCategoryId("cat_groceries_active", categories, hiddenMap);
  console.log('  Scenario A (Top Active): "cat_groceries_active" ->', resActive);
  assert.strictEqual(resActive, "cat_groceries_active");

  // Scenario B: Top prediction is HIDDEN, mapped via hiddenMap
  const resMapped = resolveCategoryId("cat_dining_old", categories, hiddenMap);
  console.log('  Scenario B (Mapped Hidden): "cat_dining_old" ->', resMapped);
  assert.strictEqual(resMapped, "cat_dining_active");

  // Scenario C: Top prediction is HIDDEN, resolved via probability scanning
  const predProb = {
    label: "cat_subs_old",
    confidence: 0.85,
    probabilities: {
      cat_subs_old: 0.85,
      cat_subs_active: 0.12,
      cat_groceries_active: 0.03,
    },
  };
  const resProb = resolveCategoryId(predProb, categories, hiddenMap);
  console.log('  Scenario C (Probability Scan): Top="cat_subs_old" -> Resolved:', resProb);
  assert.strictEqual(resProb, "cat_subs_active");

  // Scenario D: Top prediction is HIDDEN with no probability scan, resolved via keyword match
  const resKeyword = resolveCategoryId("cat_groceries_old", categories, hiddenMap);
  console.log('  Scenario D (Keyword Match): "cat_groceries_old" ->', resKeyword);
  assert.strictEqual(resKeyword, "cat_groceries_active");

  // Scenario E: Invariant check - Ensure hidden categories are NEVER returned
  categories.forEach((cat) => {
    if (cat.hidden) {
      const res = resolveCategoryId(cat.id, categories, hiddenMap);
      const isReturnedHidden = categories.find((c) => c.id === res)?.hidden ?? false;
      assert.strictEqual(
        isReturnedHidden,
        false,
        `Resolution for ${cat.id} must NEVER return a hidden category`
      );
    }
  });

  console.log("\n🎉 All Hidden Category Resolver Tests Passed Successfully!");
}

runTests();
