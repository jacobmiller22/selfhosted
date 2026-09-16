import { Type } from "@google/genai";

/**
 * Native Gemini responseSchema enforcing typed structured JSON output.
 */
export const TRANSACTION_EXTRACTION_SCHEMA = {
  type: Type.OBJECT,
  properties: {
    account_identifier: {
      type: Type.STRING,
      description:
        "Detected bank account name or card suffix from screen header, e.g., '360 Checking ...6341', 'Joint Savings ...6404', 'Venture ...9661'",
    },
    account_last_4: {
      type: Type.STRING,
      description: "Last 4 digits of bank account or card number if visible on screen (e.g. '6341', '6404', '9661')",
    },
    transactions: {
      type: Type.ARRAY,
      description: "Array of transaction records visible in the screenshot",
      items: {
        type: Type.OBJECT,
        properties: {
          date: {
            type: Type.STRING,
            description:
              "Transaction date in canonical ISO format (YYYY-MM-DD), resolved against the reference anchor date.",
          },
          payee: {
            type: Type.STRING,
            description:
              "Clean, human-readable merchant or payee name (e.g. 'Trader Joe's', 'Costco', 'Target', 'Shell').",
          },
          payee_raw: {
            type: Type.STRING,
            description:
              "Exact raw unparsed merchant line from the screenshot (e.g. 'TRADER JOES #542 SEATTLE WA').",
          },
          amount: {
            type: Type.NUMBER,
            description:
              "Transaction dollar amount with correct sign: NEGATIVE for expenses/purchases/debits (e.g. -42.50), POSITIVE for deposits/credits/inflow/refunds (e.g. 1500.00).",
          },
          amount_cents: {
            type: Type.INTEGER,
            description:
              "Transaction amount in integer cents with correct sign: NEGATIVE for expenses (e.g. -4250), POSITIVE for deposits/credits (e.g. 150000).",
          },
          status: {
            type: Type.STRING,
            enum: ["cleared", "pending"],
            description:
              "'pending' if transaction is marked as Pending, Processing, or Hold; otherwise 'cleared'.",
          },
          account_identifier: {
            type: Type.STRING,
            description: "Account or card identifier for this transaction if visible.",
          },
          notes: {
            type: Type.STRING,
            description: "Additional details, memo, location, or original description.",
          },
        },
        required: ["date", "payee", "amount", "status"],
      },
    },
  },
  required: ["transactions"],
};

/**
 * Builds the multimodal extraction prompt with dynamic reference date and custom instructions.
 */
export function buildExtractionPrompt(
  referenceDateIso: string,
  customInstructions?: string
): string {
  return [
    `You are an expert financial OCR assistant specialized in analyzing mobile banking and credit card screenshots.`,
    `Analyze this mobile banking screenshot and extract all transaction records.`,
    ``,
    `System Reference Date: ${referenceDateIso}`,
    ``,
    `### Extraction Rules:`,
    `1. **Account Identification**: Look for any account header, card nickname, or last 4 digits (e.g., '360 Checking ...6341', 'Joint Savings ...6404', 'Venture Card ...9661', 'Amex Gold'). Populate account_identifier and account_last_4.`,
    `2. **Date Resolution**: Convert all relative dates ('Today', 'Yesterday', 'Monday', 'Sep 15', '09/14') into canonical ISO dates (YYYY-MM-DD) based on the Reference Date: ${referenceDateIso}.`,
    `3. **Sign & Amount Conventions**:`,
    `   - Money spent/outflow/purchases/charges MUST BE NEGATIVE (e.g., -$42.50, amount: -42.50, amount_cents: -4250).`,
    `   - Money received/inflow/deposits/paychecks/refunds/credits MUST BE POSITIVE (e.g., +$1,250.00, amount: 1250.00, amount_cents: 125000).`,
    `4. **Payee Normalization**:`,
    `   - payee: clean, title-cased merchant name (e.g., "Trader Joe's", "Whole Foods", "Chevron").`,
    `   - payee_raw: exact verbatim text from the screen (e.g., "TRADER JOE'S #542 09/14").`,
    `5. **Transaction Status**:`,
    `   - If listed under a "Pending" / "Processing" section or badged with "Pending", set status: "pending".`,
    `   - Otherwise, set status: "cleared".`,
    `6. **Completeness**: Extract all visible transactions in chronological order from top to bottom.`,
    customInstructions ? `\n### Additional Instructions:\n${customInstructions}` : ``,
  ]
    .filter(Boolean)
    .join("\n");
}
