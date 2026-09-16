import type { ActualAccount } from "../actual.js";
import type { MappingConfig } from "../config.js";
import type { AccountMatchResult } from "./types.js";

/**
 * Extracts a 4-digit bank account or card number suffix from an identifier string.
 */
export function extractLast4Digits(identifier?: string): string | undefined {
  if (!identifier) return undefined;
  const match = identifier.match(/(?:[\.\s#\-:]+|^)(\d{4})(?:\b|$)/);
  return match ? match[1] : undefined;
}

/**
 * Matches an account identifier or last 4 digits against mappings.json and Actual Budget accounts.
 *
 * @param accountIdentifier Raw string detected from screenshot (e.g. "360 Checking ...6341", "Joint Savings", "VentureCard")
 * @param accountLast4 Explicit 4 digits if extracted separately
 * @param mappings Loaded mappings configuration
 * @param accounts Optional list of Actual Budget accounts
 */
export function matchAccountFromIdentifier(
  accountIdentifier?: string,
  accountLast4?: string,
  mappings?: MappingConfig,
  accounts?: ActualAccount[]
): AccountMatchResult {
  const identifier = (accountIdentifier || "").trim();
  const last4 = accountLast4?.trim() || extractLast4Digits(identifier);

  // Helper to resolve account name if we have account ID and accounts list
  const resolveName = (id: string): string | undefined => {
    if (!accounts) return undefined;
    const found = accounts.find((a) => a.id === id);
    return found ? found.name : undefined;
  };

  // 1. Check mappings.accountNumbers with last 4 digits
  if (last4 && mappings?.accountNumbers) {
    const matchedId = mappings.accountNumbers[last4];
    if (matchedId) {
      return {
        accountId: matchedId,
        accountName: resolveName(matchedId),
        confidence: "exact_number",
        source: `mappings.accountNumbers["${last4}"]`,
      };
    }
  }

  // 2. Check if accounts list has an account whose name contains last 4 digits
  if (last4 && accounts && accounts.length > 0) {
    const matchingAccounts = accounts.filter(
      (a) => !a.closed && a.name.includes(last4)
    );
    if (matchingAccounts.length === 1) {
      return {
        accountId: matchingAccounts[0].id,
        accountName: matchingAccounts[0].name,
        confidence: "exact_number",
        source: `accounts[name contains "${last4}"]`,
      };
    }
  }

  // 3. Check mappings.accountAliases
  const anyMappings = mappings as any;
  if (identifier && anyMappings?.accountAliases) {
    const lowerIdentifier = identifier.toLowerCase();
    for (const [alias, accountId] of Object.entries(anyMappings.accountAliases as Record<string, string>)) {
      if (lowerIdentifier.includes(alias.toLowerCase())) {
        return {
          accountId,
          accountName: resolveName(accountId),
          confidence: "alias",
          source: `mappings.accountAliases["${alias}"]`,
        };
      }
    }
  }

  // 4. Check mappings.csvProfiles keys (e.g. "Checking...9661", "JointSavings...6404")
  if (identifier && mappings?.csvProfiles) {
    const cleanId = identifier.replace(/[\s\.\-_]/g, "").toLowerCase();
    for (const profileKey of Object.keys(mappings.csvProfiles)) {
      const cleanProfile = profileKey.replace(/[\s\.\-_]/g, "").toLowerCase();
      if (cleanId.includes(cleanProfile) || cleanProfile.includes(cleanId)) {
        // If profileKey contains 4 digits, check accountNumbers
        const profileLast4 = extractLast4Digits(profileKey);
        if (profileLast4 && mappings.accountNumbers?.[profileLast4]) {
          const accountId = mappings.accountNumbers[profileLast4];
          return {
            accountId,
            accountName: resolveName(accountId),
            confidence: "alias",
            source: `mappings.csvProfiles["${profileKey}"]`,
          };
        }
      }
    }
  }

  // 5. Match against Actual Budget accounts by exact ID or name
  if (identifier && accounts && accounts.length > 0) {
    const lowerId = identifier.toLowerCase();

    // Exact ID match
    const exactIdMatch = accounts.find((a) => a.id.toLowerCase() === lowerId);
    if (exactIdMatch) {
      return {
        accountId: exactIdMatch.id,
        accountName: exactIdMatch.name,
        confidence: "name_match",
        source: "accounts[id exact]",
      };
    }

    // Exact name match
    const exactNameMatch = accounts.find(
      (a) => !a.closed && a.name.toLowerCase() === lowerId
    );
    if (exactNameMatch) {
      return {
        accountId: exactNameMatch.id,
        accountName: exactNameMatch.name,
        confidence: "name_match",
        source: "accounts[name exact]",
      };
    }

    // Substring name match
    const substringMatches = accounts.filter(
      (a) =>
        !a.closed &&
        (a.name.toLowerCase().includes(lowerId) || lowerId.includes(a.name.toLowerCase()))
    );
    if (substringMatches.length === 1) {
      return {
        accountId: substringMatches[0].id,
        accountName: substringMatches[0].name,
        confidence: "name_match",
        source: `accounts[substring "${substringMatches[0].name}"]`,
      };
    }
  }

  return {
    accountId: undefined,
    accountName: undefined,
    confidence: "none",
    source: "unresolved",
  };
}
