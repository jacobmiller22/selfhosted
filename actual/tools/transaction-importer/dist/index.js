import { Command } from "commander";
import fs from "fs";
import inquirer from "inquirer";
import path from "path";
import { connectActual, disconnectActual, fetchAccounts, fetchPayees, importTransactionsToAccount } from "./actual.js";
import { calculateAccountBalances, formatAccountBalancesTable } from "./balances.js";
import { getConfig, loadMappings } from "./config.js";
import { formatBatchSummaryTable, getFilenameBaseAndIsGeneric, resolveFileInteractively } from "./matcher.js";
import { parseStatementFile } from "./parsers/index.js";
import { OnnxPredictorEngine } from "./predictor.js";
import { detectIntraBatchTransferPairs, formatTransferPairsSummary } from "./transferMatcher.js";
const program = new Command();
program
    .name("import-transactions")
    .description("Import CSV, OFX, QFX, QBO, and QIF transaction files into Actual Budget.")
    .argument("<target-path>", "Path to a directory containing transaction files or a single transaction file")
    .option("-a, --account <accountIdOrName>", "Explicit Actual Budget account ID or name for all files")
    .option("-d, --dry-run", "Parse files and resolve accounts without modifying budget data", false)
    .option("--no-archive", "Do not move imported files to archived/ folder")
    .option("-t, --max-transfer-days <days>", "Maximum date difference in days for paired transfer matching", "5")
    .option("--no-transfers", "Disable automatic transfer pair matching")
    .action(async (targetPathArg, options) => {
    const config = getConfig();
    const mappings = loadMappings(config.mappingsPath);
    const targetPath = path.resolve(targetPathArg);
    if (!fs.existsSync(targetPath)) {
        console.error(`❌ Error: Path "${targetPath}" does not exist.`);
        process.exit(1);
    }
    let filesToProcess = [];
    const stat = fs.statSync(targetPath);
    if (stat.isFile()) {
        filesToProcess.push(targetPath);
    }
    else if (stat.isDirectory()) {
        const files = fs.readdirSync(targetPath);
        const validExts = [".csv", ".ofx", ".qfx", ".qbo", ".qif"];
        filesToProcess = files
            .filter(f => validExts.includes(path.extname(f).toLowerCase()))
            .map(f => path.join(targetPath, f));
    }
    if (filesToProcess.length === 0) {
        console.log(`ℹ️ No transaction files (.csv, .ofx, .qfx, .qbo, .qif) found in "${targetPath}".`);
        process.exit(0);
    }
    console.log(`\n🚀 Starting Actual Budget Importer...`);
    console.log(`- Server: ${config.serverUrl}`);
    console.log(`- Found ${filesToProcess.length} transaction file(s) to process.`);
    if (options.dryRun) {
        console.log(`- Mode: DRY-RUN (no changes will be committed to Actual Budget)`);
    }
    try {
        await connectActual(config.serverUrl, config.password || "", config.syncId, config.dataDir);
    }
    catch (err) {
        console.error(`❌ Failed to connect to Actual Budget server: ${err.message || err}`);
        console.error(`Please check your credentials in .env or ACTUAL_PASSWORD / ACTUAL_SYNC_ID settings.`);
        process.exit(1);
    }
    try {
        const accounts = await fetchAccounts();
        const payees = await fetchPayees();
        // Initialize ONNX predictor if model exists
        const predictor = new OnnxPredictorEngine();
        const predictorLoaded = await predictor.init();
        if (predictorLoaded) {
            console.log(`- ML Predictor: ONNX model loaded for transfer payee resolution.`);
        }
        // Phase 1 (Staging)
        console.log(`\n================ Phase 1: Staging & Account Resolution ================`);
        const stagedImports = [];
        for (const filePath of filesToProcess) {
            const filename = path.basename(filePath);
            console.log(`\n📄 Processing file: ${filename}`);
            try {
                const { base: filenameBase } = getFilenameBaseAndIsGeneric(filename);
                let savedProfile = mappings.csvProfiles?.[filename] || mappings.csvProfiles?.[filenameBase];
                let parsed = parseStatementFile(filePath, savedProfile);
                if (!parsed.accountStatements || parsed.accountStatements.length === 0) {
                    console.log(`⚠️ No valid transaction statements found in ${filename}. Skipping.`);
                    continue;
                }
                for (let i = 0; i < parsed.accountStatements.length; i++) {
                    const statement = parsed.accountStatements[i];
                    const displayFilename = parsed.accountStatements.length > 1
                        ? `${filename} [Account ${i + 1}/${parsed.accountStatements.length}${statement.accountNumber ? ` #${statement.accountNumber}` : ""}]`
                        : filename;
                    if (!statement.transactions || statement.transactions.length === 0) {
                        console.log(`⚠️ No transactions in statement block for ${displayFilename}. Skipping.`);
                        continue;
                    }
                    const interactiveResult = await resolveFileInteractively({
                        filePath,
                        statement,
                        accounts,
                        mappings,
                        mappingsPath: config.mappingsPath,
                        explicitAccountArg: options.account
                    });
                    stagedImports.push({
                        filePath,
                        filename: displayFilename,
                        statement: interactiveResult.statement || statement,
                        selectedAccount: interactiveResult.selectedAccount,
                        action: interactiveResult.action,
                        csvProfile: interactiveResult.csvProfile,
                        savedRuleDescription: interactiveResult.savedRuleDescription
                    });
                }
            }
            catch (err) {
                console.error(`❌ Error staging ${filename}: ${err.message || err}`);
            }
        }
        // Helper function to update and render review tables
        const refreshReviewState = async () => {
            const maxTransferDays = parseInt(options.maxTransferDays, 10) || 5;
            const transferPairs = options.transfers !== false
                ? await detectIntraBatchTransferPairs(stagedImports, payees, {
                    maxDateDeltaDays: maxTransferDays,
                    enablePredictor: predictorLoaded,
                    predictorEngine: predictor
                })
                : [];
            const balanceSummaries = await calculateAccountBalances(stagedImports, accounts);
            console.log(`\n================ Batch Review ================`);
            console.log(formatBatchSummaryTable(stagedImports));
            if (options.transfers !== false) {
                console.log(`\n` + formatTransferPairsSummary(transferPairs));
            }
            console.log(`\n` + formatAccountBalancesTable(balanceSummaries, "📊 PROJECTED ACCOUNT BALANCES SUMMARY"));
            return { transferPairs };
        };
        const { transferPairs } = await refreshReviewState();
        if (options.dryRun) {
            console.log(`\n[DRY-RUN] Batch review complete. No changes committed to Actual Budget.`);
            await disconnectActual();
            process.exit(0);
        }
        let reviewLoop = true;
        while (reviewLoop) {
            const commitAnswer = await inquirer.prompt([
                {
                    type: "list",
                    name: "action",
                    message: "Commit batch import into Actual Budget?",
                    choices: [
                        { name: "🚀 Yes, Commit All Imports into Actual Budget", value: "commit" },
                        { name: "↩️ Edit a Prepared File", value: "edit" },
                        { name: "❌ Cancel Batch Import (No data written)", value: "cancel" }
                    ]
                }
            ]);
            if (commitAnswer.action === "cancel") {
                console.log(`\n❌ Cancel Batch Import (No data written)`);
                await disconnectActual();
                process.exit(0);
            }
            if (commitAnswer.action === "edit") {
                if (stagedImports.length === 0) {
                    console.log(`⚠️ No prepared files available to edit.`);
                    continue;
                }
                const editChoices = [
                    ...stagedImports.map((item, idx) => ({
                        name: `${item.filename} (${item.action === "skip" || !item.selectedAccount ? "Skipped" : item.selectedAccount.name})`,
                        value: idx
                    })),
                    { name: "↩️ Back to Batch Review", value: -1 }
                ];
                const editAnswer = await inquirer.prompt([
                    {
                        type: "list",
                        name: "targetIndex",
                        message: "Select a prepared file to edit:",
                        choices: editChoices
                    }
                ]);
                if (editAnswer.targetIndex !== -1) {
                    const targetItem = stagedImports[editAnswer.targetIndex];
                    console.log(`\n⚙️ Re-running wizard for "${targetItem.filename}"...`);
                    const interactiveResult = await resolveFileInteractively({
                        filePath: targetItem.filePath,
                        statement: targetItem.statement,
                        accounts,
                        mappings,
                        mappingsPath: config.mappingsPath,
                        explicitAccountArg: options.account
                    });
                    stagedImports[editAnswer.targetIndex] = {
                        ...targetItem,
                        statement: interactiveResult.statement || targetItem.statement,
                        selectedAccount: interactiveResult.selectedAccount,
                        action: interactiveResult.action,
                        csvProfile: interactiveResult.csvProfile,
                        savedRuleDescription: interactiveResult.savedRuleDescription
                    };
                    await refreshReviewState();
                }
                continue;
            }
            if (commitAnswer.action === "commit") {
                reviewLoop = false;
            }
        }
        // Phase 2 (Execution & Archiving)
        console.log(`\n================ Phase 2: Execution & Archiving ================`);
        const successfulFilePaths = new Set();
        const importSummary = [];
        for (const item of stagedImports) {
            if (item.action === "skip" || !item.selectedAccount) {
                console.log(`⏭️ Skipping "${item.filename}" as requested.`);
                importSummary.push({
                    filename: item.filename,
                    account: "N/A",
                    count: 0,
                    status: "Skipped"
                });
                continue;
            }
            console.log(`📥 Importing ${item.statement.transactions.length} transaction(s) into account "${item.selectedAccount.name}" for "${item.filename}"...`);
            try {
                const res = await importTransactionsToAccount(item.selectedAccount.id, item.statement.transactions);
                console.log(`✅ Import complete for "${item.selectedAccount.name}"! Added: ${res.added?.length || 0}, Updated/Merged: ${res.updated?.length || 0}`);
                importSummary.push({
                    filename: item.filename,
                    account: item.selectedAccount.name,
                    count: item.statement.transactions.length,
                    status: "Imported"
                });
                successfulFilePaths.add(item.filePath);
            }
            catch (err) {
                console.error(`❌ Error importing "${item.filename}": ${err.message || err}`);
                importSummary.push({
                    filename: item.filename,
                    account: item.selectedAccount.name,
                    count: 0,
                    status: `Failed: ${err.message || err}`
                });
            }
        }
        if (options.archive && successfulFilePaths.size > 0) {
            for (const filePath of successfulFilePaths) {
                if (fs.existsSync(filePath)) {
                    const fileDir = path.dirname(filePath);
                    const archiveDir = path.join(fileDir, "archived");
                    if (!fs.existsSync(archiveDir)) {
                        fs.mkdirSync(archiveDir, { recursive: true });
                    }
                    const destPath = path.join(archiveDir, path.basename(filePath));
                    fs.renameSync(filePath, destPath);
                    console.log(`📦 Archived file to: ${destPath}`);
                }
            }
        }
        console.log(`\n================ Summary ================`);
        console.table(importSummary);
        // Display Final Updated Account Balances
        const finalBalanceSummaries = await calculateAccountBalances(stagedImports, accounts);
        console.log(`\n` + formatAccountBalancesTable(finalBalanceSummaries, "🏦 FINAL POST-IMPORT ACCOUNT BALANCES"));
        console.log(`=========================================\n`);
    }
    finally {
        await disconnectActual();
    }
});
program.parse();
