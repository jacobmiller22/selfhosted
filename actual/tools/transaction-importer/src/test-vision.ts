import {
  extractLast4Digits,
  matchAccountFromIdentifier,
} from "./vision/accountMatcher.js";
import {
  formatIsoDate,
  parseReferenceDate,
  resolveRelativeDate,
} from "./vision/dateResolver.js";
import {
  deduplicateTransactions,
  filterExistingTransactions,
  generateTransactionFingerprint,
} from "./vision/deduplicator.js";
import {
  extractTransactionsFromBatch,
  extractTransactionsFromImage,
  normalizeTransaction,
} from "./vision/extractor.js";
import {
  createMockGenAiClient,
  evaluateExtractionMetrics,
  GOLDEN_SAMPLE_CHECKING_360,
  GOLDEN_SAMPLE_VENTURE_CARD,
} from "./vision/testHarness.js";
import type { ActualAccount } from "./actual.js";
import type { MappingConfig } from "./config.js";
import type { VisionTransaction } from "./vision/types.js";

console.log("🧪 Running Vision-Based Transaction Extraction Test Suite...\n");

let passed = 0;
let failed = 0;

function assert(condition: boolean, testName: string, details?: string) {
  if (condition) {
    console.log(`  ✅ ${testName}`);
    passed++;
  } else {
    console.error(`  ❌ FAIL: ${testName} ${details ? `(${details})` : ""}`);
    failed++;
  }
}

// -----------------------------------------------------------------------------
// 1. DATE RESOLUTION TESTS
// -----------------------------------------------------------------------------
console.log("📅 1. Testing Relative Date Normalization & Resolution...");

// Anchor date: Wednesday, 2026-09-16
const anchorDate = new Date(Date.UTC(2026, 8, 16)); // Sep 16, 2026

assert(
  resolveRelativeDate("Today", anchorDate) === "2026-09-16",
  "Resolves 'Today' to anchor date (2026-09-16)"
);

assert(
  resolveRelativeDate("today", anchorDate) === "2026-09-16",
  "Resolves lowercase 'today'"
);

assert(
  resolveRelativeDate("Yesterday", anchorDate) === "2026-09-15",
  "Resolves 'Yesterday' to previous day (2026-09-15)"
);

assert(
  resolveRelativeDate("Wednesday", anchorDate) === "2026-09-16",
  "Resolves current day of week 'Wednesday' to 2026-09-16"
);

assert(
  resolveRelativeDate("Tuesday", anchorDate) === "2026-09-15",
  "Resolves 'Tuesday' to 2026-09-15"
);

assert(
  resolveRelativeDate("Monday", anchorDate) === "2026-09-14",
  "Resolves 'Monday' to 2026-09-14"
);

assert(
  resolveRelativeDate("Sunday", anchorDate) === "2026-09-13",
  "Resolves 'Sunday' to 2026-09-13"
);

assert(
  resolveRelativeDate("Friday", anchorDate) === "2026-09-11",
  "Resolves preceding 'Friday' to 2026-09-11"
);

assert(
  resolveRelativeDate("2 days ago", anchorDate) === "2026-09-14",
  "Resolves '2 days ago' to 2026-09-14"
);

assert(
  resolveRelativeDate("Sep 12", anchorDate) === "2026-09-12",
  "Resolves short month-day 'Sep 12' to 2026-09-12"
);

assert(
  resolveRelativeDate("September 10th", anchorDate) === "2026-09-10",
  "Resolves full month with ordinal 'September 10th' to 2026-09-10"
);

assert(
  resolveRelativeDate("09/10/2026", anchorDate) === "2026-09-10",
  "Resolves standard US slash date '09/10/2026'"
);

assert(
  resolveRelativeDate("2026-09-08", anchorDate) === "2026-09-08",
  "Resolves canonical ISO date '2026-09-08'"
);

// Year rollover test: Reference date in Jan 2026, transaction date is Dec 30
const janAnchor = new Date(Date.UTC(2026, 0, 3)); // Jan 3, 2026
assert(
  resolveRelativeDate("Dec 30", janAnchor) === "2025-12-30",
  "Handles year rollover boundary (Jan reference with Dec transaction -> 2025-12-30)"
);

// -----------------------------------------------------------------------------
// 2. ACCOUNT MATCHING INTEGRATION TESTS
// -----------------------------------------------------------------------------
console.log("\n🏦 2. Testing Account Matching Integration...");

const mockMappings: MappingConfig = {
  accountNumbers: {
    "6341": "checking-account-uuid-6341",
    "6404": "savings-account-uuid-6404",
    "9661": "credit-account-uuid-9661",
  },
  filenamePatterns: {},
  csvProfiles: {
    "Checking...9661": {},
    "JointSavings...6404": {},
  },
  accountAliases: {
    checking: "checking-account-uuid-6341",
    savings: "savings-account-uuid-6404",
    venture: "credit-account-uuid-9661",
  },
};

const mockAccounts: ActualAccount[] = [
  { id: "checking-account-uuid-6341", name: "Capital One 360 Checking (...6341)" },
  { id: "savings-account-uuid-6404", name: "Joint Savings (...6404)" },
  { id: "credit-account-uuid-9661", name: "Venture Card (...9661)" },
];

assert(
  extractLast4Digits("360 Checking ...6341") === "6341",
  "extractLast4Digits extracts '6341' from '360 Checking ...6341'"
);

assert(
  extractLast4Digits("Card ending in 9661") === "9661",
  "extractLast4Digits extracts '9661' from 'Card ending in 9661'"
);

const matchByLast4 = matchAccountFromIdentifier(
  "360 Checking ...6341",
  undefined,
  mockMappings,
  mockAccounts
);
assert(
  matchByLast4.accountId === "checking-account-uuid-6341" &&
    matchByLast4.confidence === "exact_number" &&
    matchByLast4.accountName === "Capital One 360 Checking (...6341)",
  "Matches '360 Checking ...6341' via mappings.accountNumbers"
);

const matchByAlias = matchAccountFromIdentifier(
  "Personal Checking",
  undefined,
  mockMappings,
  mockAccounts
);
assert(
  matchByAlias.accountId === "checking-account-uuid-6341" &&
    matchByAlias.confidence === "alias",
  "Matches 'Personal Checking' via mappings.accountAliases"
);

const matchByName = matchAccountFromIdentifier(
  "Joint Savings",
  undefined,
  { accountNumbers: {}, filenamePatterns: {}, csvProfiles: {} },
  mockAccounts
);
assert(
  matchByName.accountId === "savings-account-uuid-6404" &&
    matchByName.confidence === "name_match",
  "Matches 'Joint Savings' via ActualAccount name substring match"
);

// -----------------------------------------------------------------------------
// 3. TRANSACTION NORMALIZATION & FINGERPRINTING TESTS
// -----------------------------------------------------------------------------
console.log("\n📐 3. Testing Transaction Normalization & Signed Amounts...");

const normalizedExpense = normalizeTransaction(
  {
    date: "Today",
    payee: "Trader Joe's",
    payee_raw: "TRADER JOES #542",
    amount: -42.5,
    status: "cleared",
  },
  anchorDate,
  "6341"
);

assert(
  normalizedExpense.amount === -42.5 &&
    normalizedExpense.amount_cents === -4250 &&
    normalizedExpense.cleared === true &&
    normalizedExpense.date === "2026-09-16",
  "Normalizes negative expense amount (-$42.50 -> -4250 cents) with cleared status"
);

const normalizedDeposit = normalizeTransaction(
  {
    date: "Yesterday",
    payee: "Payroll",
    amount_cents: 250000,
    status: "cleared",
  },
  anchorDate
);

assert(
  normalizedDeposit.amount === 2500.0 &&
    normalizedDeposit.amount_cents === 250000 &&
    normalizedDeposit.date === "2026-09-15",
  "Normalizes positive deposit amount (250000 cents -> $2500.00)"
);

const normalizedPending = normalizeTransaction(
  {
    date: "Monday",
    payee: "Coffee Shop",
    amount: -5.5,
    status: "pending",
  },
  anchorDate
);

assert(
  normalizedPending.status === "pending" && normalizedPending.cleared === false,
  "Sets cleared: false for pending transactions"
);

const fp1 = generateTransactionFingerprint(normalizedExpense);
const fp2 = generateTransactionFingerprint({
  date: "2026-09-16",
  amount_cents: -4250,
  payee: "Trader Joe's",
});
assert(fp1 === fp2, "Generates stable, deterministic fingerprint across identical transactions");

// -----------------------------------------------------------------------------
// 4. DEDUPLICATION TESTS
// -----------------------------------------------------------------------------
console.log("\n🔄 4. Testing Deduplication Engine (Intra-batch & Ledger)...");

const batchWithDupes: VisionTransaction[] = [
  normalizedExpense,
  { ...normalizedExpense }, // exact duplicate
  normalizedDeposit,
  normalizedPending,
];

const dedupResult = deduplicateTransactions(batchWithDupes);
assert(
  dedupResult.uniqueTransactions.length === 3 && dedupResult.duplicateCount === 1,
  "Deduplicates identical records within a batch (4 -> 3, 1 duplicate caught)"
);

// Ledger reconciliation
const ledgerResult = filterExistingTransactions([normalizedExpense, normalizedDeposit], [
  {
    date: "2026-09-16",
    amount_cents: -4250,
    payee: "Trader Joe's",
  },
]);

assert(
  ledgerResult.novelTransactions.length === 1 &&
    ledgerResult.novelTransactions[0].payee === "Payroll" &&
    ledgerResult.existingCount === 1,
  "Filters existing ledger transactions (skips already recorded Trader Joe's)"
);

// -----------------------------------------------------------------------------
// 5. END-TO-END MOCKED EXTRACTION & EVALUATION TESTS
// -----------------------------------------------------------------------------
console.log("\n🤖 5. Testing Mocked Gemini Multimodal Extraction & Evaluation Metrics...");

// Test Golden Sample A: Capital One Checking 6341
const mockClientA = createMockGenAiClient(GOLDEN_SAMPLE_CHECKING_360.mockResponse);
const dummyBuffer = Buffer.from("dummy-image-data-png");

const resultA = await extractTransactionsFromImage(
  { buffer: dummyBuffer, mimeType: "image/png" },
  {
    client: mockClientA,
    referenceDate: GOLDEN_SAMPLE_CHECKING_360.referenceDate,
    mappings: mockMappings,
    accounts: mockAccounts,
  }
);

assert(
  resultA.account_last_4 === "6341",
  "Extracted account_last_4 matches '6341'"
);

assert(
  resultA.resolvedAccountId === "checking-account-uuid-6341",
  "Resolved account ID matches checking UUID"
);

assert(
  resultA.transactions.length === 4,
  "Extracted 4 transactions from Checking sample"
);

const metricsA = evaluateExtractionMetrics(
  resultA.transactions,
  GOLDEN_SAMPLE_CHECKING_360.expectedTransactions
);

assert(metricsA.precision === 1.0, `Precision is 100% (${metricsA.precision * 100}%)`);
assert(metricsA.recall === 1.0, `Recall is 100% (${metricsA.recall * 100}%)`);
assert(metricsA.f1 === 1.0, `F1 Score is 1.0 (${metricsA.f1})`);
assert(metricsA.dateAccuracy === 1.0, `Date Accuracy is 100% (${metricsA.dateAccuracy * 100}%)`);
assert(metricsA.amountAccuracy === 1.0, `Amount Accuracy is 100% (${metricsA.amountAccuracy * 100}%)`);
assert(metricsA.statusAccuracy === 1.0, `Status Accuracy is 100% (${metricsA.statusAccuracy * 100}%)`);

// Test Golden Sample B: Capital One Venture Card 9661
const mockClientB = createMockGenAiClient(GOLDEN_SAMPLE_VENTURE_CARD.mockResponse);
const resultB = await extractTransactionsFromImage(
  { buffer: dummyBuffer, mimeType: "image/png" },
  {
    client: mockClientB,
    referenceDate: GOLDEN_SAMPLE_VENTURE_CARD.referenceDate,
    mappings: mockMappings,
    accounts: mockAccounts,
  }
);

assert(
  resultB.resolvedAccountId === "credit-account-uuid-9661",
  "Resolved account ID matches credit card UUID"
);

const metricsB = evaluateExtractionMetrics(
  resultB.transactions,
  GOLDEN_SAMPLE_VENTURE_CARD.expectedTransactions
);
assert(metricsB.precision === 1.0 && metricsB.recall === 1.0, "Sample B Precision & Recall are 100%");

// -----------------------------------------------------------------------------
// 6. BATCH PROCESSING WITH OVERLAPPING SCREENSHOTS
// -----------------------------------------------------------------------------
console.log("\n📦 6. Testing Batch Screenshot Extraction & Overlap Deduplication...");

// Create simulated scrolling screenshot: Screenshot 1 + Screenshot 2 with 1 overlapping transaction
const batchClient = {
  models: {
    generateContent: async () => {
      // Alternate between sample A and a partially overlapping slice
      return {
        text: JSON.stringify(GOLDEN_SAMPLE_CHECKING_360.mockResponse),
      };
    },
  },
};

const batchResult = await extractTransactionsFromBatch(
  [
    { buffer: dummyBuffer, mimeType: "image/png" },
    { buffer: dummyBuffer, mimeType: "image/png" }, // exact duplicate screenshot
  ],
  {
    client: batchClient,
    referenceDate: "2026-09-16",
    mappings: mockMappings,
    accounts: mockAccounts,
  }
);

assert(
  batchResult.imageResults.length === 2,
  "Processed 2 images in batch"
);
assert(
  batchResult.allTransactions.length === 8,
  "Captured 8 raw transactions total across 2 images"
);
assert(
  batchResult.deduplicatedTransactions.length === 4,
  "Cleanly deduplicated 8 transactions down to 4 unique transactions"
);
assert(
  batchResult.duplicateCount === 4,
  "Accurately flagged 4 duplicate transactions"
);

// -----------------------------------------------------------------------------
// SUMMARY
// -----------------------------------------------------------------------------
console.log("\n=======================================================");
console.log(`📊 Test Results: ${passed} Passed, ${failed} Failed`);
console.log("=======================================================");

if (failed > 0) {
  console.error("❌ Some vision tests failed!");
  process.exit(1);
} else {
  console.log("🎉 ALL VISION TESTS PASSED CLEANLY!");
}
