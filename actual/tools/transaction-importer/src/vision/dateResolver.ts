/**
 * Deterministic Date Normalizer and Relative Date Resolver for Banking Screenshots.
 *
 * Resolves dates such as "Today", "Yesterday", "Monday", "Sep 15", "09/15", and ISO dates
 * relative to an anchor reference date (capture timestamp or server clock).
 */

const MONTH_NAMES: Record<string, number> = {
  jan: 0,
  january: 0,
  feb: 1,
  february: 1,
  mar: 2,
  march: 2,
  apr: 3,
  april: 3,
  may: 4,
  jun: 5,
  june: 5,
  jul: 6,
  july: 6,
  aug: 7,
  august: 7,
  sep: 8,
  sept: 8,
  september: 8,
  oct: 9,
  october: 9,
  nov: 10,
  november: 10,
  dec: 11,
  december: 11,
};

const DAY_OF_WEEK_NAMES: Record<string, number> = {
  sun: 0,
  sunday: 0,
  mon: 1,
  monday: 1,
  tue: 2,
  tues: 2,
  tuesday: 2,
  wed: 3,
  wednesday: 3,
  thu: 4,
  thur: 4,
  thurs: 4,
  thursday: 4,
  fri: 5,
  friday: 5,
  sat: 6,
  saturday: 6,
};

/**
 * Parses reference date into a valid Date object with time zeroed in local/UTC.
 */
export function parseReferenceDate(ref?: Date | string): Date {
  if (!ref) {
    const now = new Date();
    return new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  }
  if (typeof ref === "string") {
    // If ISO string like YYYY-MM-DD
    const isoMatch = ref.trim().match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (isoMatch) {
      const year = parseInt(isoMatch[1], 10);
      const month = parseInt(isoMatch[2], 10) - 1;
      const day = parseInt(isoMatch[3], 10);
      return new Date(Date.UTC(year, month, day));
    }
    const parsed = new Date(ref);
    if (!isNaN(parsed.getTime())) {
      if (parsed.getUTCHours() === 0 && parsed.getUTCMinutes() === 0) {
        return new Date(Date.UTC(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate()));
      }
      return new Date(Date.UTC(parsed.getFullYear(), parsed.getMonth(), parsed.getDate()));
    }
  }
  if (ref instanceof Date) {
    if (ref.getUTCHours() === 0 && ref.getUTCMinutes() === 0 && ref.getUTCSeconds() === 0) {
      return new Date(Date.UTC(ref.getUTCFullYear(), ref.getUTCMonth(), ref.getUTCDate()));
    }
    return new Date(Date.UTC(ref.getFullYear(), ref.getMonth(), ref.getDate()));
  }
  const fallback = new Date();
  return new Date(Date.UTC(fallback.getFullYear(), fallback.getMonth(), fallback.getDate()));
}

/**
 * Formats a Date object to YYYY-MM-DD.
 */
export function formatIsoDate(date: Date): string {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/**
 * Resolves a date string (relative, short, or ISO) to canonical YYYY-MM-DD.
 *
 * @param rawDate String extracted from OCR/screenshot (e.g. "Today", "Yesterday", "Monday", "Sep 15", "09/14/2026")
 * @param reference Anchor date (defaults to current date)
 */
export function resolveRelativeDate(rawDate: string, reference?: Date | string): string {
  const refDate = parseReferenceDate(reference);
  if (!rawDate || typeof rawDate !== "string") {
    return formatIsoDate(refDate);
  }

  const cleaned = rawDate
    .trim()
    .toLowerCase()
    .replace(/[,\.]/g, "")
    .replace(/\s+/g, " ")
    .replace(/(\d+)(st|nd|rd|th)/g, "$1"); // remove ordinals e.g. 1st -> 1

  // 1. Direct ISO match: YYYY-MM-DD
  const isoMatch = cleaned.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (isoMatch) {
    const y = parseInt(isoMatch[1], 10);
    const m = parseInt(isoMatch[2], 10) - 1;
    const d = parseInt(isoMatch[3], 10);
    return formatIsoDate(new Date(Date.UTC(y, m, d)));
  }

  // 2. Relative keywords: Today / Yesterday
  if (cleaned === "today" || cleaned.startsWith("today ")) {
    return formatIsoDate(refDate);
  }

  if (cleaned === "yesterday" || cleaned.startsWith("yesterday ")) {
    const yesterday = new Date(refDate.getTime());
    yesterday.setUTCDate(yesterday.getUTCDate() - 1);
    return formatIsoDate(yesterday);
  }

  // 3. Days of the week: Monday, Tuesday, etc.
  // In banking activity feeds, day of week refers to the most recent occurrence on or prior to the reference date
  const dayWords = cleaned.split(" ");
  const firstWord = dayWords[0];
  if (firstWord in DAY_OF_WEEK_NAMES) {
    const targetDay = DAY_OF_WEEK_NAMES[firstWord];
    const currentDay = refDate.getUTCDay();
    let diff = (currentDay - targetDay + 7) % 7;
    // If diff is 0, it's today (e.g., feed says "Wednesday" on Wednesday)
    const targetDate = new Date(refDate.getTime());
    targetDate.setUTCDate(targetDate.getUTCDate() - diff);
    return formatIsoDate(targetDate);
  }

  // 4. "X days ago"
  const daysAgoMatch = cleaned.match(/^(\d+)\s*days?\s*ago$/);
  if (daysAgoMatch) {
    const days = parseInt(daysAgoMatch[1], 10);
    const targetDate = new Date(refDate.getTime());
    targetDate.setUTCDate(targetDate.getUTCDate() - days);
    return formatIsoDate(targetDate);
  }

  // 5. Month Name + Day (e.g., "Sep 15", "September 15 2026", "15 Sep")
  // Check "Month Day Year?"
  const monthDayMatch = cleaned.match(/^([a-z]+)\s+(\d{1,2})(?:\s+(\d{2,4}))?$/);
  if (monthDayMatch && monthDayMatch[1] in MONTH_NAMES) {
    const m = MONTH_NAMES[monthDayMatch[1]];
    const d = parseInt(monthDayMatch[2], 10);
    let y = monthDayMatch[3] ? parseInt(monthDayMatch[3], 10) : refDate.getUTCFullYear();
    if (y < 100) y += 2000;

    // If no year specified, handle year rollover (e.g. Ref is Jan 2026, date is Dec 28 -> 2025)
    if (!monthDayMatch[3]) {
      const refMonth = refDate.getUTCMonth();
      if (refMonth < 2 && m > 9) {
        y -= 1;
      }
    }

    return formatIsoDate(new Date(Date.UTC(y, m, d)));
  }

  // Check "Day Month Year?" (e.g. "15 Sep" or "15 Sep 2026")
  const dayMonthMatch = cleaned.match(/^(\d{1,2})\s+([a-z]+)(?:\s+(\d{2,4}))?$/);
  if (dayMonthMatch && dayMonthMatch[2] in MONTH_NAMES) {
    const d = parseInt(dayMonthMatch[1], 10);
    const m = MONTH_NAMES[dayMonthMatch[2]];
    let y = dayMonthMatch[3] ? parseInt(dayMonthMatch[3], 10) : refDate.getUTCFullYear();
    if (y < 100) y += 2000;

    if (!dayMonthMatch[3]) {
      const refMonth = refDate.getUTCMonth();
      if (refMonth < 2 && m > 9) {
        y -= 1;
      }
    }

    return formatIsoDate(new Date(Date.UTC(y, m, d)));
  }

  // 6. Numeric dates: MM/DD/YYYY or MM/DD or MM-DD
  const slashMatch = cleaned.match(/^(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?$/);
  if (slashMatch) {
    const m = parseInt(slashMatch[1], 10) - 1;
    const d = parseInt(slashMatch[2], 10);
    let y = slashMatch[3] ? parseInt(slashMatch[3], 10) : refDate.getUTCFullYear();
    if (y < 100) y += 2000;

    if (!slashMatch[3]) {
      const refMonth = refDate.getUTCMonth();
      if (refMonth < 2 && m > 9) {
        y -= 1;
      }
    }

    return formatIsoDate(new Date(Date.UTC(y, m, d)));
  }

  // Fallback: Attempt Date.parse
  const fallback = new Date(rawDate);
  if (!isNaN(fallback.getTime())) {
    return formatIsoDate(new Date(Date.UTC(fallback.getFullYear(), fallback.getMonth(), fallback.getDate())));
  }

  // Final fallback to reference date
  return formatIsoDate(refDate);
}
