import { GoogleGenAI } from "@google/genai";
import fs from "fs";
import path from "path";
import { matchAccountFromIdentifier } from "./accountMatcher.js";
import { formatIsoDate, parseReferenceDate, resolveRelativeDate } from "./dateResolver.js";
import { deduplicateTransactions, generateTransactionFingerprint } from "./deduplicator.js";
import { buildExtractionPrompt, TRANSACTION_EXTRACTION_SCHEMA } from "./prompts.js";
import type {
  BatchVisionResult,
  RawExtractedTransaction,
  RawVisionExtractionResponse,
  VisionExtractionResult,
  VisionExtractOptions,
  VisionTransaction,
} from "./types.js";

/**
 * Determines MIME type from file extension.
 */
export function getMimeTypeFromPath(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase();
  switch (ext) {
    case ".png":
      return "image/png";
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".webp":
      return "image/webp";
    case ".heic":
      return "image/heic";
    case ".gif":
      return "image/gif";
    default:
      return "image/png";
  }
}

/**
 * Checks if a file path corresponds to a supported image file format.
 */
export function isImageFile(filePath: string): boolean {
  const ext = path.extname(filePath).toLowerCase();
  return [".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif"].includes(ext);
}

/**
 * Helper to normalize raw transaction data into a strictly typed VisionTransaction.
 */
export function normalizeTransaction(
  raw: RawExtractedTransaction,
  referenceDate: Date,
  accountHint?: string
): VisionTransaction {
  const dateIso = resolveRelativeDate(raw.date, referenceDate);

  // Normalize amount and amount_cents
  let amount = typeof raw.amount === "number" ? raw.amount : 0;
  let amountCents =
    typeof raw.amount_cents === "number" ? raw.amount_cents : Math.round(amount * 100);

  // Ensure sign alignment between amount and amountCents
  if (amount < 0 && amountCents > 0) {
    amountCents = -amountCents;
  } else if (amount > 0 && amountCents < 0) {
    amount = amountCents / 100;
  } else if (amount === 0 && amountCents !== 0) {
    amount = amountCents / 100;
  }

  const status = raw.status === "pending" ? "pending" : "cleared";
  const payee = (raw.payee || raw.payee_raw || "Unknown Payee").trim();
  const payeeRaw = (raw.payee_raw || raw.payee || payee).trim();
  const accountIdentifier = raw.account_identifier || accountHint;

  const tx: VisionTransaction = {
    date: dateIso,
    payee,
    payee_raw: payeeRaw,
    amount,
    amount_cents: amountCents,
    status,
    cleared: status === "cleared",
    account_identifier: accountIdentifier,
    notes: raw.notes || `Original: ${payeeRaw}`,
  };

  tx.imported_id = generateTransactionFingerprint(tx);
  return tx;
}

/**
 * Extracts transactions from a single image (file path or buffer) using Gemini Multimodal Vision.
 */
export async function extractTransactionsFromImage(
  input: string | Buffer | { buffer: Buffer; mimeType: string },
  options: VisionExtractOptions = {}
): Promise<VisionExtractionResult> {
  const refDate = parseReferenceDate(options.referenceDate);
  const refDateIso = formatIsoDate(refDate);

  let base64Data: string;
  let mimeType: string;
  let filePath: string | undefined;

  if (typeof input === "string") {
    filePath = path.resolve(input);
    if (!fs.existsSync(filePath)) {
      throw new Error(`Vision extraction error: File not found at "${filePath}"`);
    }
    const buffer = fs.readFileSync(filePath);
    base64Data = buffer.toString("base64");
    mimeType = getMimeTypeFromPath(filePath);
  } else if (Buffer.isBuffer(input)) {
    base64Data = input.toString("base64");
    mimeType = "image/png";
  } else if (input && typeof input === "object" && "buffer" in input) {
    base64Data = input.buffer.toString("base64");
    mimeType = input.mimeType || "image/png";
  } else {
    throw new Error("Invalid input provided for image extraction. Expected file path or Buffer.");
  }

  const modelName =
    options.model || process.env.GEMINI_MODEL || "gemini-2.5-flash";
  const apiKey =
    options.apiKey || process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY;

  let rawResponse: RawVisionExtractionResponse;

  if (options.client) {
    // Injected client for unit / evaluation testing
    const ai = options.client;
    const prompt = buildExtractionPrompt(refDateIso, options.customPrompt);
    const response = await ai.models.generateContent({
      model: modelName,
      contents: [
        {
          inlineData: {
            data: base64Data,
            mimeType,
          },
        },
        prompt,
      ],
      config: {
        responseMimeType: "application/json",
        responseSchema: TRANSACTION_EXTRACTION_SCHEMA,
      },
    });

    const text = response.text || "{}";
    rawResponse = typeof text === "string" ? JSON.parse(text) : (text as any);
  } else {
    if (!apiKey) {
      throw new Error(
        "GEMINI_API_KEY or GOOGLE_API_KEY is required for vision extraction. Please set it in your environment or .env file."
      );
    }

    const ai = new GoogleGenAI({ apiKey });
    const prompt = buildExtractionPrompt(refDateIso, options.customPrompt);

    const response = await ai.models.generateContent({
      model: modelName,
      contents: [
        {
          inlineData: {
            data: base64Data,
            mimeType,
          },
        },
        prompt,
      ],
      config: {
        responseMimeType: "application/json",
        responseSchema: TRANSACTION_EXTRACTION_SCHEMA,
      },
    });

    const text = response.text || "{}";
    rawResponse = JSON.parse(text) as RawVisionExtractionResponse;
  }

  // Account matching
  const accountHint = rawResponse.account_identifier;
  const last4 = rawResponse.account_last_4;
  const matchResult = matchAccountFromIdentifier(
    accountHint,
    last4,
    options.mappings,
    options.accounts
  );

  // Normalize transactions
  const normalizedTransactions: VisionTransaction[] = (
    rawResponse.transactions || []
  ).map((t) => normalizeTransaction(t, refDate, accountHint));

  return {
    filePath,
    account_identifier: rawResponse.account_identifier,
    account_last_4: rawResponse.account_last_4,
    resolvedAccountId: matchResult.accountId,
    resolvedAccountName: matchResult.accountName,
    accountMatchConfidence: matchResult.confidence,
    transactions: normalizedTransactions,
    rawResponse,
  };
}

/**
 * Extracts transactions from a batch of mobile screenshots, resolving accounts and deduplicating records.
 */
export async function extractTransactionsFromBatch(
  inputs: Array<string | Buffer | { buffer: Buffer; mimeType: string }>,
  options: VisionExtractOptions = {}
): Promise<BatchVisionResult> {
  const imageResults: VisionExtractionResult[] = [];
  const allTransactions: VisionTransaction[] = [];

  for (const input of inputs) {
    const result = await extractTransactionsFromImage(input, options);
    imageResults.push(result);
    allTransactions.push(...result.transactions);
  }

  const { uniqueTransactions, duplicateCount } =
    deduplicateTransactions(allTransactions);

  return {
    imageResults,
    allTransactions,
    deduplicatedTransactions: uniqueTransactions,
    duplicateCount,
  };
}
