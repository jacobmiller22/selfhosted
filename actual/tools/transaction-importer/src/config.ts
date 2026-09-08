import dotenv from 'dotenv';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config();

export interface CsvProfile {
  dateHeader?: string;
  payeeHeader?: string;
  amountHeader?: string;
  outflowHeader?: string;
  inflowHeader?: string;
  typeHeader?: string;
  notesHeader?: string;
  acctHeader?: string;
  idHeader?: string;
}

export interface MappingConfig {
  accountNumbers: Record<string, string>;
  filenamePatterns: Record<string, string>;
  csvProfiles: Record<string, CsvProfile>;
}

export interface AppConfig {
  serverUrl: string;
  password?: string;
  syncId: string;
  dataDir?: string;
  mappingsPath: string;
}

export function getConfig(): AppConfig {
  const serverUrl = process.env.ACTUAL_SERVER_URL || 'https://budget.cloud.jacobmiller22.com';
  const password = process.env.ACTUAL_PASSWORD || '';
  const syncId = process.env.ACTUAL_SYNC_ID || 'a2bf28aa-7ae9-4948-837c-346f4e91d346';
  const dataDir = process.env.ACTUAL_DATA_DIR;

  const rootConfigDir = path.resolve(__dirname, '../config');
  if (!fs.existsSync(rootConfigDir)) {
    fs.mkdirSync(rootConfigDir, { recursive: true });
  }

  const mappingsPath = path.join(rootConfigDir, 'mappings.json');
  return {
    serverUrl,
    password,
    syncId,
    dataDir,
    mappingsPath
  };
}

export function loadMappings(mappingsPath: string): MappingConfig {
  if (!fs.existsSync(mappingsPath)) {
    const initial: MappingConfig = { accountNumbers: {}, filenamePatterns: {}, csvProfiles: {} };
    fs.writeFileSync(mappingsPath, JSON.stringify(initial, null, 2), 'utf-8');
    return initial;
  }
  try {
    const raw = fs.readFileSync(mappingsPath, 'utf-8');
    const parsed = JSON.parse(raw);
    return {
      accountNumbers: parsed.accountNumbers || {},
      filenamePatterns: parsed.filenamePatterns || {},
      csvProfiles: parsed.csvProfiles || {}
    };
  } catch (err) {
    return { accountNumbers: {}, filenamePatterns: {}, csvProfiles: {} };
  }
}

export function saveMappings(mappingsPath: string, mappings: MappingConfig): void {
  fs.writeFileSync(mappingsPath, JSON.stringify(mappings, null, 2), 'utf-8');
}
