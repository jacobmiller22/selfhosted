import type { ActualAccount } from "../actual.js";
import type { MappingConfig } from "../config.js";

/**
 * Status of an extracted transaction.
 */
export type TransactionStatus = "cleared" | "pending";

/**
 * Normalized transaction extracted from a mobile banking screenshot.
 */
export interface VisionTransaction {
  /** ISO date string: YYYY-MM-DD */
  date: string;
  /** Cleaned/normalized merchant or payee name */
  payee: string;
  /** Original unparsed raw merchant text from image */
  payee_raw: string;
  /** Transaction amount in dollars (negative for expenses/outflows, positive for deposits/credits) */
  amount: number;
  /** Transaction amount in integer cents (e.g. -4250 for -$42.50) */
  amount_cents: number;
  /** Status: cleared or pending */
  status: TransactionStatus;
  /** Boolean cleared flag (true if status === 'cleared') */
  cleared: boolean;
  /** Account identifier detected on image (e.g. '6341', 'Checking', 'VentureCard') */
  account_identifier?: string;
  /** Additional notes, category clues, or raw description */
  notes?: string;
  /** Deterministic fingerprint for deduplication */
  imported_id?: string;
}

/**
 * Raw transaction structure expected from Gemini structured responseSchema.
 */
export interface RawExtractedTransaction {
  date: string;
  payee: string;
  payee_raw?: string;
  amount?: number;
  amount_cents?: number;
  status: "cleared" | "pending";
  account_identifier?: string;
  notes?: string;
}

/**
 * Raw top-level payload enforced by Gemini structured schema.
 */
export interface RawVisionExtractionResponse {
  account_identifier?: string;
  account_last_4?: string;
  transactions: RawExtractedTransaction[];
}

/**
 * Result of matching an account identifier against configurations and Actual Budget.
 */
export interface AccountMatchResult {
  accountId?: string;
  accountName?: string;
  confidence: "exact_number" | "alias" | "name_match" | "none";
  source: string;
}

/**
 * Full extraction result for a single image.
 */
export interface VisionExtractionResult {
  filePath?: string;
  account_identifier?: string;
  account_last_4?: string;
  resolvedAccountId?: string;
  resolvedAccountName?: string;
  accountMatchConfidence?: "exact_number" | "alias" | "name_match" | "none";
  transactions: VisionTransaction[];
  rawResponse?: RawVisionExtractionResponse;
}

/**
 * Aggregated result from processing a batch of images.
 */
export interface BatchVisionResult {
  imageResults: VisionExtractionResult[];
  allTransactions: VisionTransaction[];
  deduplicatedTransactions: VisionTransaction[];
  duplicateCount: number;
}

/**
 * Configuration options for Vision extraction.
 */
export interface VisionExtractOptions {
  /** Gemini model ID (defaults to 'gemini-2.5-flash' or GEMINI_MODEL env) */
  model?: string;
  /** API key override (defaults to GEMINI_API_KEY or GOOGLE_API_KEY env) */
  apiKey?: string;
  /** Reference anchor date for resolving relative dates like 'Today', 'Yesterday' (default: current Date) */
  referenceDate?: Date | string;
  /** Mapping configuration (from mappings.json) */
  mappings?: MappingConfig;
  /** List of Actual Budget accounts for matching */
  accounts?: ActualAccount[];
  /** Custom additional prompt instructions */
  customPrompt?: string;
  /** Injected GoogleGenAI instance for testing or custom auth */
  client?: any;
}
