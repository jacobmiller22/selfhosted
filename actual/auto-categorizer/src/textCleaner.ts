const PREFIX_PATTERNS = [
  /^sq\s*\*\s*/i,
  /^tst\s*\*\s*/i,
  /^paypal\s*\*\s*/i,
  /^py\s*\*\s*/i,
  /^sp\s*\*\s*/i,
  /^chk\s*card\s*/i,
  /^debit\s*card\s*purchase\s*/i,
  /^pos\s*purchase\s*/i,
  /^recurring\s*payment\s*/i,
  /^ach\s*withdrawal\s*/i,
  /^direct\s*deposit\s*/i,
];

const SUFFIX_PATTERNS = [
  /#\s*\d+/gi,
  /\b\d{3}-\d{3}-\d{4}\b/gi,
  /\b[A-Z]{2}\s+\d{5}\b/gi,
  /\b(ca|ny|tx|fl|wa|or|il|ma|nc|ga)\b/gi,
  /\b\d{2}\/\d{2}\b/gi,
];

export function cleanPayeeText(text: string | null | undefined): string {
  if (!text || typeof text !== "string") {
    return "";
  }

  let cleaned = text.toLowerCase().trim();

  for (const pat of PREFIX_PATTERNS) {
    cleaned = cleaned.replace(pat, "");
  }

  for (const pat of SUFFIX_PATTERNS) {
    cleaned = cleaned.replace(pat, "");
  }

  // Replace non-alphanumeric with spaces
  cleaned = cleaned.replace(/[^\w\s]/g, " ");

  // Collapse multiple spaces
  cleaned = cleaned.replace(/\s+/g, " ").trim();

  return cleaned || text.toLowerCase().trim();
}
