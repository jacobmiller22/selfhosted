/**
 * Normalizes QIF date formats into YYYY-MM-DD.
 * Handles:
 * - YYYY-MM-DD
 * - YYYYMMDD
 * - MM/DD/YYYY or M/D/YYYY
 * - MM/DD'YYYY or M/D'YYYY
 * - MM/DD'YY or M/D'YY
 * - MM/DD/YY or M/D/YY
 */
export function normalizeQifDate(rawDate) {
    const cleaned = rawDate.trim();
    // YYYY-MM-DD
    let match = cleaned.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
    if (match) {
        const [, y, m, d] = match;
        return `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
    }
    // YYYYMMDD
    match = cleaned.match(/^(\d{4})(\d{2})(\d{2})$/);
    if (match) {
        const [, y, m, d] = match;
        return `${y}-${m}-${d}`;
    }
    // MM/DD'YYYY or M/D'YYYY or MM/DD/YYYY or M/D/YYYY
    match = cleaned.match(/^(\d{1,2})[\/'\.](\d{1,2})[\/'\.](\d{4})$/);
    if (match) {
        const [, m, d, y] = match;
        return `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
    }
    // MM/DD'YY or M/D'YY or MM/DD/YY or M/D/YY
    match = cleaned.match(/^(\d{1,2})[\/'\.](\d{1,2})[\/'\.](\d{2})$/);
    if (match) {
        const [, m, d, yy] = match;
        const yyNum = parseInt(yy, 10);
        const fullYear = yyNum >= 70 ? 1900 + yyNum : 2000 + yyNum;
        return `${fullYear}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
    }
    return cleaned;
}
export function parseQifContent(content) {
    const accountStatements = [];
    let currentAccountNumber = undefined;
    let currentTransactions = [];
    // Split content into records separated by '^'
    const blocks = content.split('^');
    for (const block of blocks) {
        const lines = block
            .split(/\r?\n/)
            .map(line => line.trim())
            .filter(line => line.length > 0);
        if (lines.length === 0)
            continue;
        let isAccountBlock = false;
        let accountNameInBlock = undefined;
        let rawDate;
        let rawAmount;
        let payee_name;
        let memo;
        let category;
        let imported_id;
        let cleared;
        if (lines.some(l => l.startsWith('!Account'))) {
            isAccountBlock = true;
        }
        for (const line of lines) {
            if (line.startsWith('!Account')) {
                isAccountBlock = true;
                continue;
            }
            if (line.startsWith('!Type:')) {
                isAccountBlock = false;
                continue;
            }
            if (line.startsWith('!')) {
                continue;
            }
            const code = line[0];
            const val = line.substring(1).trim();
            if (isAccountBlock) {
                if (code === 'N' && val) {
                    accountNameInBlock = val;
                }
            }
            else {
                switch (code) {
                    case 'D':
                        rawDate = val;
                        break;
                    case 'T':
                    case 'U':
                        if (!rawAmount || code === 'T') {
                            rawAmount = val;
                        }
                        break;
                    case 'P':
                        payee_name = val;
                        break;
                    case 'M':
                        memo = val;
                        break;
                    case 'L':
                        category = val;
                        break;
                    case 'N':
                        imported_id = val;
                        break;
                    case 'C': {
                        const status = val.toLowerCase();
                        if (['*', 'c', 'x', 'r', 'cleared', 'yes', '1', 'true'].includes(status) || status.length > 0) {
                            cleared = true;
                        }
                        else {
                            cleared = false;
                        }
                        break;
                    }
                }
            }
        }
        if (isAccountBlock) {
            if (currentTransactions.length > 0) {
                accountStatements.push({
                    accountNumber: currentAccountNumber,
                    transactions: currentTransactions
                });
                currentTransactions = [];
            }
            if (accountNameInBlock) {
                currentAccountNumber = accountNameInBlock;
            }
        }
        else if (rawDate && rawAmount !== undefined) {
            const date = normalizeQifDate(rawDate);
            const cleanAmountStr = rawAmount.replace(/,/g, '');
            const parsedFloat = parseFloat(cleanAmountStr);
            if (date && !isNaN(parsedFloat)) {
                const amount = Math.round(parsedFloat * 100);
                let notes;
                if (memo && category) {
                    notes = `${memo} - ${category}`;
                }
                else {
                    notes = memo || category || undefined;
                }
                currentTransactions.push({
                    date,
                    amount,
                    payee_name: payee_name || undefined,
                    imported_id: imported_id || undefined,
                    notes,
                    cleared
                });
            }
        }
    }
    if (currentTransactions.length > 0 || accountStatements.length === 0) {
        accountStatements.push({
            accountNumber: currentAccountNumber,
            transactions: currentTransactions
        });
    }
    return {
        accountStatements
    };
}
