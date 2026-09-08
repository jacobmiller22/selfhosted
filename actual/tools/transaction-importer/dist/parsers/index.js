import fs from 'fs';
import path from 'path';
import { parseCsvContent } from './csv.js';
import { parseOfxContent } from './ofx.js';
import { parseQifContent } from './qif.js';
export function parseStatementFile(filePath, profile) {
    const ext = path.extname(filePath).toLowerCase();
    const content = fs.readFileSync(filePath, 'utf-8');
    if (ext === '.qif') {
        return parseQifContent(content);
    }
    if (ext === '.ofx' || ext === '.qfx' || ext === '.qbo') {
        return parseOfxContent(content);
    }
    if (ext === '.csv') {
        return parseCsvContent(content, path.basename(filePath), profile);
    }
    if (content.includes('!Type:') || content.includes('!Account')) {
        return parseQifContent(content);
    }
    if (content.includes('<OFX>') || content.includes('<STMTTRN>')) {
        return parseOfxContent(content);
    }
    return parseCsvContent(content, path.basename(filePath), profile);
}
