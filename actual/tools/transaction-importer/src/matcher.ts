import inquirer from "inquirer";
import path from "path";
import { ActualAccount } from "./actual.js";
import { CsvProfile, MappingConfig, saveMappings } from "./config.js";
import { parseStatementFile, type AccountStatement } from "./parsers/index.js";

export type WizardStep = "CSV_MAPPING" | "ACCOUNT_SELECTION" | "GENERIC_RULE" | "REVIEW";

export interface ResolveFileInteractiveOptions {
  filePath: string;
  statement: AccountStatement;
  accounts: ActualAccount[];
  mappings: MappingConfig;
  mappingsPath: string;
  explicitAccountArg?: string;
}

export interface ResolveFileInteractiveResult {
  action: "import" | "skip";
  selectedAccount?: ActualAccount;
  statement?: AccountStatement;
  csvProfile?: CsvProfile;
  savedRuleDescription?: string;
}

export interface StagedImport {
  filePath: string;
  filename: string;
  statement: AccountStatement;
  selectedAccount?: ActualAccount;
  action: "import" | "skip";
  csvProfile?: CsvProfile;
  savedRuleDescription?: string;
}

export function formatBatchSummaryTable(stagedImports: StagedImport[]): string {
  if (!stagedImports || stagedImports.length === 0) {
    return [
      `┌───────────────────────────────────────────────────────────┐`,
      `│ 📊 BATCH IMPORT SUMMARY                                   │`,
      `├───────────────────────────────────────────────────────────┤`,
      `│ (No staged imports)                                       │`,
      `└───────────────────────────────────────────────────────────┘`
    ].join("\n");
  }

  const colHeaders = {
    filename: "File Name",
    account: "Account Name",
    count: "Transaction Count",
    dateRange: "Date Range",
    netFlow: "Net Flow"
  };

  const rows = stagedImports.map(item => {
    const filename = item.filename;
    const accountName = item.action === "skip" || !item.selectedAccount
      ? "(Skipped)"
      : item.selectedAccount.name;
    const txs = item.statement?.transactions || [];
    const count = txs.length;

    let dateRange = "N/A";
    if (count > 0) {
      const dates = txs.map(t => t.date).filter(Boolean).sort();
      if (dates.length > 0) {
        const minDate = dates[0];
        const maxDate = dates[dates.length - 1];
        dateRange = minDate === maxDate ? minDate : `${minDate} to ${maxDate}`;
      }
    }

    let netFlow = "$0.00";
    if (count > 0 && item.action !== "skip") {
      const netCents = txs.reduce((sum, t) => sum + (t.amount || 0), 0);
      const dollars = (Math.abs(netCents) / 100).toFixed(2);
      if (netCents > 0) {
        netFlow = `+$${dollars}`;
      } else if (netCents < 0) {
        netFlow = `-$${dollars}`;
      } else {
        netFlow = `$0.00`;
      }
    }

    return {
      filename,
      accountName,
      countStr: count.toString(),
      dateRange,
      netFlow
    };
  });

  let wFile = colHeaders.filename.length;
  let wAcc = colHeaders.account.length;
  let wCount = colHeaders.count.length;
  let wDate = colHeaders.dateRange.length;
  let wNet = colHeaders.netFlow.length;

  for (const r of rows) {
    if (r.filename.length > wFile) wFile = r.filename.length;
    if (r.accountName.length > wAcc) wAcc = r.accountName.length;
    if (r.countStr.length > wCount) wCount = r.countStr.length;
    if (r.dateRange.length > wDate) wDate = r.dateRange.length;
    if (r.netFlow.length > wNet) wNet = r.netFlow.length;
  }

  const pad = (str: string, width: number) => str.padEnd(width);

  const topBorder    = `┌─${"─".repeat(wFile)}─┬─${"─".repeat(wAcc)}─┬─${"─".repeat(wCount)}─┬─${"─".repeat(wDate)}─┬─${"─".repeat(wNet)}─┐`;
  const headerRow    = `│ ${pad(colHeaders.filename, wFile)} │ ${pad(colHeaders.account, wAcc)} │ ${pad(colHeaders.count, wCount)} │ ${pad(colHeaders.dateRange, wDate)} │ ${pad(colHeaders.netFlow, wNet)} │`;
  const headerSep    = `├─${"─".repeat(wFile)}─┼─${"─".repeat(wAcc)}─┼─${"─".repeat(wCount)}─┼─${"─".repeat(wDate)}─┼─${"─".repeat(wNet)}─┤`;
  const bottomBorder = `└─${"─".repeat(wFile)}─┴─${"─".repeat(wAcc)}─┴─${"─".repeat(wCount)}─┴─${"─".repeat(wDate)}─┴─${"─".repeat(wNet)}─┘`;

  const lines: string[] = [];
  lines.push(topBorder);
  lines.push(headerRow);
  lines.push(headerSep);
  for (const r of rows) {
    lines.push(`│ ${pad(r.filename, wFile)} │ ${pad(r.accountName, wAcc)} │ ${pad(r.countStr, wCount)} │ ${pad(r.dateRange, wDate)} │ ${pad(r.netFlow, wNet)} │`);
  }
  lines.push(bottomBorder);

  return lines.join("\n");
}

export function formatCsvMappingRundown(
  headersOrStatement: CsvProfile | AccountStatement,
  filename?: string
): string {
  let headers: CsvProfile = {};
  if ("detectedHeaders" in headersOrStatement && headersOrStatement.detectedHeaders) {
    headers = headersOrStatement.detectedHeaders;
  } else {
    headers = headersOrStatement as CsvProfile;
  }

  const lines: string[] = [];
  lines.push(`┌─────────────────────────────────────────────────────────────┐`);
  lines.push(`│ 📋 CSV COLUMN MAPPING RUNDOWN                               │`);
  lines.push(`├─────────────────────────────────────────────────────────────┤`);
  if (filename) {
    lines.push(`│ 📄 File: ${filename}`);
  }
  lines.push(`│ 📅 Date:          ${headers.dateHeader || "(None)"}`);
  lines.push(`│ 👤 Payee:         ${headers.payeeHeader || "(None)"}`);
  lines.push(`│ 💸 Outflow:       ${headers.outflowHeader || "(None)"}`);
  lines.push(`│ 💰 Inflow:        ${headers.inflowHeader || "(None)"}`);
  lines.push(`│ 💵 Single Amount: ${headers.amountHeader || "(None)"}`);
  lines.push(`│ 🏷️ Type Field:    ${headers.typeHeader || "(None)"}`);
  lines.push(`│ 📝 Notes:         ${headers.notesHeader || "(None)"}`);
  lines.push(`└─────────────────────────────────────────────────────────────┘`);

  return lines.join("\n");
}

export async function promptForCsvProfile(
  csvHeaders: string[],
  currentHeaders: CsvProfile = {},
  filename?: string
): Promise<CsvProfile> {
  const choices = ["(None)", ...csvHeaders];

  console.log(`\n⚙️ Customize CSV Column Mapping for ${filename || "file"}:`);

  const answers = await inquirer.prompt([
    {
      type: "list",
      name: "dateHeader",
      message: "Select Date column:",
      choices,
      default: currentHeaders.dateHeader && csvHeaders.includes(currentHeaders.dateHeader) ? currentHeaders.dateHeader : "(None)"
    },
    {
      type: "list",
      name: "payeeHeader",
      message: "Select Payee / Description column:",
      choices,
      default: currentHeaders.payeeHeader && csvHeaders.includes(currentHeaders.payeeHeader) ? currentHeaders.payeeHeader : "(None)"
    },
    {
      type: "list",
      name: "outflowHeader",
      message: "Select Outflow / Expense column:",
      choices,
      default: currentHeaders.outflowHeader && csvHeaders.includes(currentHeaders.outflowHeader) ? currentHeaders.outflowHeader : "(None)"
    },
    {
      type: "list",
      name: "inflowHeader",
      message: "Select Inflow / Deposit column:",
      choices,
      default: currentHeaders.inflowHeader && csvHeaders.includes(currentHeaders.inflowHeader) ? currentHeaders.inflowHeader : "(None)"
    },
    {
      type: "list",
      name: "amountHeader",
      message: "Select Single Amount column:",
      choices,
      default: currentHeaders.amountHeader && csvHeaders.includes(currentHeaders.amountHeader) ? currentHeaders.amountHeader : "(None)"
    },
    {
      type: "list",
      name: "typeHeader",
      message: "Select Transaction Type column:",
      choices,
      default: currentHeaders.typeHeader && csvHeaders.includes(currentHeaders.typeHeader) ? currentHeaders.typeHeader : "(None)"
    },
    {
      type: "list",
      name: "notesHeader",
      message: "Select Notes / Memo column:",
      choices,
      default: currentHeaders.notesHeader && csvHeaders.includes(currentHeaders.notesHeader) ? currentHeaders.notesHeader : "(None)"
    }
  ]);

  const profile: CsvProfile = {
    dateHeader: answers.dateHeader === "(None)" ? undefined : answers.dateHeader,
    payeeHeader: answers.payeeHeader === "(None)" ? undefined : answers.payeeHeader,
    outflowHeader: answers.outflowHeader === "(None)" ? undefined : answers.outflowHeader,
    inflowHeader: answers.inflowHeader === "(None)" ? undefined : answers.inflowHeader,
    amountHeader: answers.amountHeader === "(None)" ? undefined : answers.amountHeader,
    typeHeader: answers.typeHeader === "(None)" ? undefined : answers.typeHeader,
    notesHeader: answers.notesHeader === "(None)" ? undefined : answers.notesHeader
  };

  return profile;
}

export function formatTransactionPreview(
  statement: AccountStatement,
  filename?: string
): string {
  const count = statement.transactions.length;
  if (count === 0) {
    return [
      `┌───────────────────────────────────────────────────────────┐`,
      `│ 📊 TRANSACTION PREVIEW                                   │`,
      `├───────────────────────────────────────────────────────────┤`,
      ...(filename ? [`│ 📄 File: ${filename}`] : []),
      `│ 💳 Account #: ${statement.accountNumber || "None detected"}`,
      `│ 🔢 Transactions: 0`,
      `└───────────────────────────────────────────────────────────┘`
    ].join("\n");
  }

  const dates = statement.transactions.map(t => t.date).filter(Boolean).sort();
  const minDate = dates[0] || "N/A";
  const maxDate = dates[dates.length - 1] || "N/A";
  const dateRange = minDate === maxDate ? minDate : `${minDate} to ${maxDate}`;

  const netCents = statement.transactions.reduce((sum, t) => sum + (t.amount || 0), 0);
  const netDollars = (Math.abs(netCents) / 100).toFixed(2);
  const formattedNet = netCents < 0 ? `-$${netDollars}` : `$${netDollars}`;

  const samples = statement.transactions.slice(0, 3).map(t => {
    const payee = t.payee_name || "(No Payee)";
    const dollars = (Math.abs(t.amount) / 100).toFixed(2);
    const amtStr = t.amount < 0 ? `-$${dollars}` : `$${dollars}`;
    return `${t.date} | ${payee} | ${amtStr}`;
  });

  const lines: string[] = [];
  lines.push(`┌─────────────────────────────────────────────────────────────┐`);
  lines.push(`│ 📊 TRANSACTION PREVIEW                                      │`);
  lines.push(`├─────────────────────────────────────────────────────────────┤`);
  if (filename) {
    lines.push(`│ 📄 File: ${filename}`);
  }
  lines.push(`│ 💳 Account #: ${statement.accountNumber || "None detected"}`);
  lines.push(`│ 🔢 Transactions: ${count}`);
  lines.push(`│ 📅 Date Range: ${dateRange}`);
  lines.push(`│ 💵 Net Total: ${formattedNet}`);
  lines.push(`│`);
  lines.push(`│ 🔍 Top 3 Sample Payees:`);
  for (const sample of samples) {
    lines.push(`│   • ${sample}`);
  }
  lines.push(`└─────────────────────────────────────────────────────────────┘`);

  return lines.join("\n");
}

export function formatFinalReviewBox(params: {
  filename: string;
  accountName: string;
  isCsv: boolean;
  csvOutflowInflow?: string;
  ruleToSave: string;
}): string {
  const lines: string[] = [];
  lines.push(`┌─────────────────────────────────────────────────────────────┐`);
  lines.push(`│ 📋 FINAL REVIEW FOR "${params.filename}"`);
  lines.push(`├─────────────────────────────────────────────────────────────┤`);
  lines.push(`│ 🏦 Selected Account: ${params.accountName}`);
  if (params.isCsv) {
    lines.push(`│ 📄 CSV Outflow/Inflow: ${params.csvOutflowInflow || "None"}`);
  }
  lines.push(`│ 💾 Rule to Save: ${params.ruleToSave}`);
  lines.push(`└─────────────────────────────────────────────────────────────┘`);
  return lines.join("\n");
}

export function getRuleToSaveDescription(params: {
  statement?: AccountStatement;
  saveRule: boolean;
  isGeneric: boolean;
  filename?: string;
  filenameBase?: string;
  genericMatchChoice: "exact" | "none";
}): string {
  const { statement, saveRule, isGeneric, genericMatchChoice } = params;

  if (!saveRule) {
    return "Do not save rule";
  }

  if (statement?.accountNumber) {
    return `Match account number (${statement.accountNumber})`;
  }

  if (isGeneric) {
    if (genericMatchChoice === "exact") {
      return "Match exact filename";
    }
    return "Do not save filename rule";
  }

  return "Match filename base";
}

export function getNextWizardStep(
  currentStep: WizardStep,
  choice: string,
  context: { isCsv: boolean; isGeneric: boolean; saveRule: boolean; hasAccount: boolean }
): WizardStep {
  if (currentStep === "CSV_MAPPING") {
    if (choice === "keep" || choice === "customize") {
      return context.hasAccount ? "REVIEW" : "ACCOUNT_SELECTION";
    }
  }

  if (currentStep === "ACCOUNT_SELECTION") {
    if (choice === "__GOBACK__") {
      return context.isCsv ? "CSV_MAPPING" : "ACCOUNT_SELECTION";
    }
    if (choice === "select") {
      if (context.saveRule && context.isGeneric) {
        return "GENERIC_RULE";
      }
      return "REVIEW";
    }
  }

  if (currentStep === "GENERIC_RULE") {
    if (choice === "__GOBACK__") {
      return "ACCOUNT_SELECTION";
    }
    if (choice === "select") {
      return "REVIEW";
    }
  }

  if (currentStep === "REVIEW") {
    if (choice === "edit_account") {
      return "ACCOUNT_SELECTION";
    }
    if (choice === "edit_csv") {
      return "CSV_MAPPING";
    }
  }

  return currentStep;
}

export async function resolveFileInteractively(
  options: ResolveFileInteractiveOptions
): Promise<ResolveFileInteractiveResult> {
  const { filePath, accounts, mappings, mappingsPath, explicitAccountArg } = options;
  let currentStatement = options.statement;
  const filename = path.basename(filePath);
  const ext = path.extname(filePath).toLowerCase();
  const isCsv = ext === ".csv";
  const { base: filenameBase, isGeneric } = getFilenameBaseAndIsGeneric(filename);

  let savedCsvProfile = mappings.csvProfiles?.[filename] || mappings.csvProfiles?.[filenameBase];
  let currentCsvProfile: CsvProfile = savedCsvProfile || currentStatement.detectedHeaders || {};

  let selectedAccount: ActualAccount | undefined;
  let autoMatched = false;

  if (explicitAccountArg) {
    const match = accounts.find(
      a => a.id === explicitAccountArg || a.name.toLowerCase() === explicitAccountArg.toLowerCase()
    );
    if (match) {
      selectedAccount = match;
      autoMatched = true;
    } else {
      console.warn(`⚠️ Specified account "${explicitAccountArg}" not found in budget. Falling back to matching engine.`);
    }
  }

  if (!selectedAccount && currentStatement.accountNumber) {
    const mappedId = mappings.accountNumbers[currentStatement.accountNumber];
    if (mappedId) {
      const match = accounts.find(a => a.id === mappedId);
      if (match) {
        console.log(`✓ Matched account number "${currentStatement.accountNumber}" -> "${match.name}"`);
        selectedAccount = match;
        autoMatched = true;
      }
    }
    if (!selectedAccount) {
      const directMatch = accounts.find(
        a => a.name.includes(currentStatement.accountNumber!) || a.id === currentStatement.accountNumber
      );
      if (directMatch) {
        console.log(`✓ Inferred account "${currentStatement.accountNumber}" -> "${directMatch.name}"`);
        selectedAccount = directMatch;
        autoMatched = true;
      }
    }
  }

  if (!selectedAccount) {
    for (const [pattern, accountId] of Object.entries(mappings.filenamePatterns)) {
      const regex = new RegExp(pattern, "i");
      if (regex.test(filename)) {
        const match = accounts.find(a => a.id === accountId);
        if (match) {
          console.log(`✓ Matched filename pattern "${pattern}" -> "${match.name}"`);
          selectedAccount = match;
          autoMatched = true;
          break;
        }
      }
    }
  }

  if (autoMatched && selectedAccount && (!isCsv || savedCsvProfile)) {
    return {
      action: "import",
      selectedAccount,
      statement: currentStatement,
      csvProfile: currentCsvProfile,
      savedRuleDescription: "Auto-matched existing rule"
    };
  }

  let step: WizardStep = (isCsv && !savedCsvProfile) ? "CSV_MAPPING" : (selectedAccount ? "REVIEW" : "ACCOUNT_SELECTION");
  let shouldSaveRule = true;
  let genericMatchChoice: "exact" | "none" = "exact";

  while (true) {
    if (step === "CSV_MAPPING") {
      console.log("\n" + formatCsvMappingRundown(currentCsvProfile, filename));

      const choices = [
        { name: "✅ Keep current mapping", value: "keep" },
        { name: "⚙️ Customize columns", value: "customize" }
      ];

      const mappingAnswer = await inquirer.prompt([
        {
          type: "list",
          name: "mappingConfirm",
          message: "Is this CSV column mapping correct?",
          choices
        }
      ]);

      if (mappingAnswer.mappingConfirm === "customize") {
        const headers = currentStatement.csvHeaders || [];
        currentCsvProfile = await promptForCsvProfile(headers, currentCsvProfile, filename);
        const reParsed = parseStatementFile(filePath, currentCsvProfile);
        if (reParsed.accountStatements && reParsed.accountStatements.length > 0) {
          currentStatement = reParsed.accountStatements[0];
        }
      }

      step = getNextWizardStep("CSV_MAPPING", mappingAnswer.mappingConfirm, {
        isCsv,
        isGeneric,
        saveRule: shouldSaveRule,
        hasAccount: !!selectedAccount
      });
      continue;
    }

    if (step === "ACCOUNT_SELECTION") {
      console.log(`\n❓ Could not auto-detect Actual Budget account for file: ${filename}`);
      console.log(formatTransactionPreview(currentStatement, filename));

      const activeAccounts = accounts.filter(a => !a.closed);

      const choices = [
        ...activeAccounts.map(a => ({
          name: `${a.name} (${a.type || "account"})`,
          value: a.id
        })),
        ...(isCsv ? [{ name: "↩️ Edit CSV Column Mappings (Go Back)", value: "__GOBACK__" }] : [])
      ];

      const accountAnswer = await inquirer.prompt([
        {
          type: "list",
          name: "accountId",
          message: `Select Actual Budget account for "${filename}"${currentStatement.accountNumber ? ` (Account #${currentStatement.accountNumber})` : ""}:`,
          choices
        }
      ]);

      if (accountAnswer.accountId === "__GOBACK__") {
        step = getNextWizardStep("ACCOUNT_SELECTION", "__GOBACK__", {
          isCsv,
          isGeneric,
          saveRule: shouldSaveRule,
          hasAccount: !!selectedAccount
        });
        continue;
      }

      selectedAccount = accounts.find(a => a.id === accountAnswer.accountId)!;

      const defaultSaveRule = shouldSaveRule;
      const saveRulePromptAnswer: { confirmSaveRule: boolean } = await inquirer.prompt<{ confirmSaveRule: boolean }> ([
        {
          type: "confirm",
          name: "confirmSaveRule",
          message: "Would you like to remember this mapping rule for future imports?",
          default: defaultSaveRule
        }
      ]);

      shouldSaveRule = saveRulePromptAnswer.confirmSaveRule;

      step = getNextWizardStep("ACCOUNT_SELECTION", "select", {
        isCsv,
        isGeneric,
        saveRule: shouldSaveRule,
        hasAccount: !!selectedAccount
      });
      continue;
    }

    if (step === "GENERIC_RULE") {
      const genericAnswer = await inquirer.prompt([
        {
          type: "list",
          name: "matchType",
          message: `⚠️ "${filename}" is a generic export filename ("${filenameBase}"). How should this rule match future files?`,
          choices: [
            {
              name: `Match exact filename only (^${escapeRegExp(filename)}$)`,
              value: "exact"
            },
            {
              name: `Do not save filename rule (prompt every time for generic filenames)`,
              value: "none"
            },
            {
              name: "↩️ Go Back",
              value: "__GOBACK__"
            }
          ]
        }
      ]);

      if (genericAnswer.matchType === "__GOBACK__") {
        step = getNextWizardStep("GENERIC_RULE", "__GOBACK__", {
          isCsv,
          isGeneric,
          saveRule: shouldSaveRule,
          hasAccount: !!selectedAccount
        });
        continue;
      }

      genericMatchChoice = genericAnswer.matchType;
      step = getNextWizardStep("GENERIC_RULE", "select", {
        isCsv,
        isGeneric,
        saveRule: shouldSaveRule,
        hasAccount: !!selectedAccount
      });
      continue;
    }

    if (step === "REVIEW") {
      if (!selectedAccount) {
        step = "ACCOUNT_SELECTION";
        continue;
      }

      let csvOutflowInflow: string | undefined;
      if (isCsv) {
        if (currentCsvProfile.outflowHeader || currentCsvProfile.inflowHeader) {
          csvOutflowInflow = `${currentCsvProfile.outflowHeader || "(None)"} / ${currentCsvProfile.inflowHeader || "(None)"}`;
        } else if (currentCsvProfile.amountHeader) {
          csvOutflowInflow = `Single Amount: ${currentCsvProfile.amountHeader}`;
        } else {
          csvOutflowInflow = "None";
        }
      }

      const ruleToSaveDescription = getRuleToSaveDescription({
        statement: currentStatement,
        saveRule: shouldSaveRule,
        isGeneric,
        filename,
        filenameBase,
        genericMatchChoice
      });

      console.log("\n" + formatFinalReviewBox({
        filename,
        accountName: selectedAccount.name,
        isCsv,
        csvOutflowInflow,
        ruleToSave: ruleToSaveDescription
      }));

      const reviewChoices = [
        { name: "✅ Confirm & Continue", value: "confirm" },
        { name: "↩️ Edit Account Selection", value: "edit_account" },
        ...(isCsv ? [{ name: "↩️ Edit CSV Column Mappings", value: "edit_csv" }] : []),
        { name: "⏭️ Skip this file", value: "skip" }
      ];

      const reviewAnswer = await inquirer.prompt([
        {
          type: "list",
          name: "reviewChoice",
          message: "Review selection and confirm:",
          choices: reviewChoices
        }
      ]);

      if (reviewAnswer.reviewChoice === "edit_account" || reviewAnswer.reviewChoice === "edit_csv") {
        step = getNextWizardStep("REVIEW", reviewAnswer.reviewChoice, {
          isCsv,
          isGeneric,
          saveRule: shouldSaveRule,
          hasAccount: !!selectedAccount
        });
        continue;
      } else if (reviewAnswer.reviewChoice === "skip") {
        return { action: "skip" };
      } else if (reviewAnswer.reviewChoice === "confirm") {
        if (isCsv && currentCsvProfile) {
          mappings.csvProfiles = mappings.csvProfiles || {};
          mappings.csvProfiles[filenameBase || filename] = currentCsvProfile;
        }

        if (shouldSaveRule) {
          if (currentStatement.accountNumber) {
            mappings.accountNumbers[currentStatement.accountNumber] = selectedAccount.id;
            console.log(`💾 Saved account number mapping rule "${currentStatement.accountNumber}" -> "${selectedAccount.name}" to ${mappingsPath}`);
          } else if (isGeneric) {
            if (genericMatchChoice === "exact") {
              const pattern = `^${escapeRegExp(filename)}$`;
              mappings.filenamePatterns[pattern] = selectedAccount.id;
              console.log(`💾 Saved filename mapping rule "${pattern}" -> "${selectedAccount.name}" to ${mappingsPath}`);
            }
          } else {
            const pattern = `^${escapeRegExp(filenameBase)}`;
            mappings.filenamePatterns[pattern] = selectedAccount.id;
            console.log(`💾 Saved filename mapping rule "${pattern}" -> "${selectedAccount.name}" to ${mappingsPath}`);
          }
        }

        saveMappings(mappingsPath, mappings);

        return {
          action: "import",
          selectedAccount,
          statement: currentStatement,
          csvProfile: isCsv ? currentCsvProfile : undefined,
          savedRuleDescription: ruleToSaveDescription
        };
      }
    }
  }
}

export async function resolveAccountForFile(
  filePath: string,
  statement: AccountStatement,
  accounts: ActualAccount[],
  mappings: MappingConfig,
  mappingsPath: string,
  explicitAccountArg?: string
): Promise<ActualAccount> {
  const result = await resolveFileInteractively({
    filePath,
    statement,
    accounts,
    mappings,
    mappingsPath,
    explicitAccountArg
  });

  if (result.action === "skip" || !result.selectedAccount) {
    throw new Error(`File processing skipped by user for ${path.basename(filePath)}`);
  }

  return result.selectedAccount;
}

export function getFilenameBaseAndIsGeneric(filename: string): { base: string; isGeneric: boolean } {
  let nameWithoutExt = path.basename(filename, path.extname(filename));

  const dateRegex = /(\d{4}[-_.]?\d{2}[-_.]?\d{2}|\d{8})/g;
  nameWithoutExt = nameWithoutExt.replace(dateRegex, "");

  nameWithoutExt = nameWithoutExt.replace(/\s*\(\d+\)$/, "").replace(/[-_]\d+$/, "");

  const cleanedBase = nameWithoutExt.replace(/^[-_.\s]+|[-_.\s]+$/g, "");

  const GENERIC_KEYWORDS = [
    "download",
    "transaction",
    "transactions",
    "statement",
    "export",
    "creditcard",
    "checking",
    "savings",
    "activity",
    "history",
    "account"
  ];

  const tokens = cleanedBase.toLowerCase().split(/[-_.\s]+/).filter(Boolean);

  const nonGenericTokens = tokens.filter(
    token => !GENERIC_KEYWORDS.includes(token) && !/^\d+$/.test(token)
  );

  const isNumeric = /^\d+$/.test(cleanedBase);
  const isTooShort = cleanedBase.length <= 2;
  const isGeneric = !cleanedBase || isNumeric || isTooShort || nonGenericTokens.length === 0;

  return {
    base: cleanedBase || filename,
    isGeneric
  };
}

function escapeRegExp(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
