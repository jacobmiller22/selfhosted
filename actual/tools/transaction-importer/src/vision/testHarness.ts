import type {
  RawVisionExtractionResponse,
  VisionTransaction,
} from "./types.js";

/**
 * Golden sample definitions representing real-world mobile screenshots.
 */
export interface GoldenSample {
  id: string;
  name: string;
  description: string;
  referenceDate: string;
  mockResponse: RawVisionExtractionResponse;
  expectedTransactions: VisionTransaction[];
}

export const GOLDEN_SAMPLE_CHECKING_360: GoldenSample = {
  id: "capital-one-checking-6341",
  name: "Capital One 360 Checking (...6341)",
  description: "Checking account feed with mixed debits, payroll deposit, pending hold, and relative dates.",
  referenceDate: "2026-09-16", // Wednesday
  mockResponse: {
    account_identifier: "360 Checking ...6341",
    account_last_4: "6341",
    transactions: [
      {
        date: "Today",
        payee: "Trader Joe's",
        payee_raw: "TRADER JOES #542 SEATTLE WA",
        amount: -42.5,
        amount_cents: -4250,
        status: "cleared",
        notes: "Original: TRADER JOES #542 SEATTLE WA",
      },
      {
        date: "Yesterday",
        payee: "Acme Payroll Direct Deposit",
        payee_raw: "ACME CORP PAYROLL DIR DEP",
        amount: 2500.0,
        amount_cents: 250000,
        status: "cleared",
        notes: "Direct deposit payroll",
      },
      {
        date: "Monday",
        payee: "Blue Bottle Coffee",
        payee_raw: "BLUE BOTTLE COFFEE SEATTLE",
        amount: -6.75,
        amount_cents: -675,
        status: "pending",
        notes: "Pending debit card transaction",
      },
      {
        date: "Sep 12",
        payee: "Chevron",
        payee_raw: "CHEVRON 0092441 SEATTLE WA",
        amount: -35.0,
        amount_cents: -3500,
        status: "cleared",
        notes: "Fuel purchase",
      },
    ],
  },
  expectedTransactions: [
    {
      date: "2026-09-16",
      payee: "Trader Joe's",
      payee_raw: "TRADER JOES #542 SEATTLE WA",
      amount: -42.5,
      amount_cents: -4250,
      status: "cleared",
      cleared: true,
      account_identifier: "360 Checking ...6341",
      notes: "Original: TRADER JOES #542 SEATTLE WA",
    },
    {
      date: "2026-09-15",
      payee: "Acme Payroll Direct Deposit",
      payee_raw: "ACME CORP PAYROLL DIR DEP",
      amount: 2500.0,
      amount_cents: 250000,
      status: "cleared",
      cleared: true,
      account_identifier: "360 Checking ...6341",
      notes: "Direct deposit payroll",
    },
    {
      date: "2026-09-14",
      payee: "Blue Bottle Coffee",
      payee_raw: "BLUE BOTTLE COFFEE SEATTLE",
      amount: -6.75,
      amount_cents: -675,
      status: "pending",
      cleared: false,
      account_identifier: "360 Checking ...6341",
      notes: "Pending debit card transaction",
    },
    {
      date: "2026-09-12",
      payee: "Chevron",
      payee_raw: "CHEVRON 0092441 SEATTLE WA",
      amount: -35.0,
      amount_cents: -3500,
      status: "cleared",
      cleared: true,
      account_identifier: "360 Checking ...6341",
      notes: "Fuel purchase",
    },
  ],
};

export const GOLDEN_SAMPLE_VENTURE_CARD: GoldenSample = {
  id: "capital-one-venture-9661",
  name: "Capital One Venture (...9661)",
  description: "Credit card feed with retail charges and merchant return credit.",
  referenceDate: "2026-09-16",
  mockResponse: {
    account_identifier: "Venture Card ...9661",
    account_last_4: "9661",
    transactions: [
      {
        date: "Today",
        payee: "Amazon",
        payee_raw: "AMZN MKTP US*2K9184",
        amount: -58.99,
        amount_cents: -5899,
        status: "pending",
        notes: "Pending online charge",
      },
      {
        date: "Yesterday",
        payee: "Target",
        payee_raw: "TARGET T-0914 SEATTLE WA",
        amount: -89.2,
        amount_cents: -8920,
        status: "cleared",
        notes: "In-store shopping",
      },
      {
        date: "Sep 10",
        payee: "REI Co-op Return",
        payee_raw: "REI CO-OP ONLINE RETURN",
        amount: 45.0,
        amount_cents: 4500,
        status: "cleared",
        notes: "Merchant return credit",
      },
    ],
  },
  expectedTransactions: [
    {
      date: "2026-09-16",
      payee: "Amazon",
      payee_raw: "AMZN MKTP US*2K9184",
      amount: -58.99,
      amount_cents: -5899,
      status: "pending",
      cleared: false,
      account_identifier: "Venture Card ...9661",
      notes: "Pending online charge",
    },
    {
      date: "2026-09-15",
      payee: "Target",
      payee_raw: "TARGET T-0914 SEATTLE WA",
      amount: -89.2,
      amount_cents: -8920,
      status: "cleared",
      cleared: true,
      account_identifier: "Venture Card ...9661",
      notes: "In-store shopping",
    },
    {
      date: "2026-09-10",
      payee: "REI Co-op Return",
      payee_raw: "REI CO-OP ONLINE RETURN",
      amount: 45.0,
      amount_cents: 4500,
      status: "cleared",
      cleared: true,
      account_identifier: "Venture Card ...9661",
      notes: "Merchant return credit",
    },
  ],
};

/**
 * Creates a mock GoogleGenAI client returning prescribed responses for deterministic testing.
 */
export function createMockGenAiClient(
  responseMap: Record<string, RawVisionExtractionResponse> | RawVisionExtractionResponse
): any {
  return {
    models: {
      generateContent: async (params: any) => {
        let resp: RawVisionExtractionResponse;
        if ("transactions" in responseMap) {
          resp = responseMap as RawVisionExtractionResponse;
        } else {
          // If mapping by keyword in prompt or image
          const contentsStr = JSON.stringify(params.contents || "");
          const key = Object.keys(responseMap).find((k) => contentsStr.includes(k));
          resp = key ? responseMap[key] : Object.values(responseMap)[0];
        }
        return {
          text: JSON.stringify(resp),
        };
      },
    },
  };
}

/**
 * Computes precision, recall, and accuracy metrics comparing extracted against expected.
 */
export function evaluateExtractionMetrics(
  extracted: VisionTransaction[],
  expected: VisionTransaction[]
): {
  precision: number;
  recall: number;
  f1: number;
  dateAccuracy: number;
  amountAccuracy: number;
  statusAccuracy: number;
  totalExpected: number;
  totalExtracted: number;
  matchedCount: number;
} {
  let truePositives = 0;
  let correctDates = 0;
  let correctAmounts = 0;
  let correctStatuses = 0;

  for (const exp of expected) {
    // Match by amount and normalized payee
    const match = extracted.find(
      (act) =>
        act.amount_cents === exp.amount_cents &&
        act.payee.toLowerCase().includes(exp.payee.toLowerCase().split(" ")[0])
    );

    if (match) {
      truePositives++;
      if (match.date === exp.date) correctDates++;
      if (match.amount_cents === exp.amount_cents) correctAmounts++;
      if (match.status === exp.status) correctStatuses++;
    }
  }

  const precision = extracted.length > 0 ? truePositives / extracted.length : 0;
  const recall = expected.length > 0 ? truePositives / expected.length : 0;
  const f1 =
    precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;

  return {
    precision,
    recall,
    f1,
    dateAccuracy: truePositives > 0 ? correctDates / truePositives : 0,
    amountAccuracy: truePositives > 0 ? correctAmounts / truePositives : 0,
    statusAccuracy: truePositives > 0 ? correctStatuses / truePositives : 0,
    totalExpected: expected.length,
    totalExtracted: extracted.length,
    matchedCount: truePositives,
  };
}
