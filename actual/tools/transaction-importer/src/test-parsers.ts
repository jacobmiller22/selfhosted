import path from 'path';
import { parseStatementFile } from './parsers/index.js';
import { parseCsvContent } from './parsers/csv.js';
import { parseQifContent } from './parsers/qif.js';
import { parseOfxContent } from './parsers/ofx.js';
import {
  formatCsvMappingRundown,
  formatTransactionPreview,
  formatFinalReviewBox,
  getRuleToSaveDescription,
  getNextWizardStep,
  formatBatchSummaryTable,
  type StagedImport
} from './matcher.js';
import type { CsvProfile } from './config.js';

console.log('🧪 Testing Transaction Statement Parsers & Enhancements...\n');

// 1. Existing Sample File Tests
const ofxPath = path.resolve('test-samples/sample_checking.ofx');
const parsedOfx = parseStatementFile(ofxPath);

console.log(`📄 Parsed OFX File: sample_checking.ofx`);
console.log(`   Account Statements Count: ${parsedOfx.accountStatements.length}`);
console.log(`   Account Number: ${parsedOfx.accountStatements[0]?.accountNumber}`);
console.log(`   Transaction Count: ${parsedOfx.accountStatements[0]?.transactions.length}`);

const csvPath = path.resolve('test-samples/sample_credit.csv');
const parsedCsv = parseStatementFile(csvPath);

console.log(`\n📄 Parsed CSV File: sample_credit.csv`);
console.log(`   Account Statements Count: ${parsedCsv.accountStatements.length}`);
console.log(`   Account Number: ${parsedCsv.accountStatements[0]?.accountNumber || 'None (CSV header)'}`);
console.log(`   Transaction Count: ${parsedCsv.accountStatements[0]?.transactions.length}`);

const qifPath = path.resolve('test-samples/sample_checking.qif');
const parsedQif = parseStatementFile(qifPath);

console.log(`\n📄 Parsed QIF File: sample_checking.qif`);
console.log(`   Account Statements Count: ${parsedQif.accountStatements.length}`);
console.log(`   Account Number: ${parsedQif.accountStatements[0]?.accountNumber}`);
console.log(`   Transaction Count: ${parsedQif.accountStatements[0]?.transactions.length}`);

if (
  parsedOfx.accountStatements.length === 1 &&
  parsedOfx.accountStatements[0].transactions.length === 2 &&
  parsedCsv.accountStatements.length === 1 &&
  parsedCsv.accountStatements[0].transactions.length === 2 &&
  parsedQif.accountStatements.length === 1 &&
  parsedQif.accountStatements[0].transactions.length === 5 &&
  parsedQif.accountStatements[0].accountNumber === '555444333'
) {
  console.log('✅ Standard file parser tests passed!');
} else {
  console.error('❌ Standard file parser tests failed!');
  process.exit(1);
}

// 2. Multi-Account QIF Test
console.log('\n🧪 Testing Multi-Account QIF Parsing...');
const multiQifContent = `
!Account
NCHECKING_101
TBank
^
!Type:Bank
D08/01/2026
T-25.00
PStore A
^
!Account
NSAVINGS_202
TBank
^
!Type:Bank
D08/02/2026
T100.00
PInterest Income
^
D08/03/2026
T50.00
PTransfer In
^
`;

const multiQifParsed = parseQifContent(multiQifContent);
console.log(`   Account Statements Found: ${multiQifParsed.accountStatements.length}`);
if (
  multiQifParsed.accountStatements.length === 2 &&
  multiQifParsed.accountStatements[0].accountNumber === 'CHECKING_101' &&
  multiQifParsed.accountStatements[0].transactions.length === 1 &&
  multiQifParsed.accountStatements[1].accountNumber === 'SAVINGS_202' &&
  multiQifParsed.accountStatements[1].transactions.length === 2
) {
  console.log('✅ Multi-Account QIF parsing test passed!');
} else {
  console.error('❌ Multi-Account QIF parsing test failed!', JSON.stringify(multiQifParsed, null, 2));
  process.exit(1);
}

// 3. Multi-Account OFX Test
console.log('\n🧪 Testing Multi-Account OFX Parsing...');
const multiOfxContent = `
OFXHEADER:100
DATA:OFXSGML
VERSION:102
<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<BANKACCTFROM>
<ACCTID>ACCT_CHECKING_101
</BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260801
<TRNAMT>-50.00
<FITID>1001
<NAME>Store A
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
<STMTTRNRS>
<STMTRS>
<BANKACCTFROM>
<ACCTID>ACCT_SAVINGS_202
</BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260802
<TRNAMT>200.00
<FITID>2001
<NAME>Deposit
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
`;

const multiOfxParsed = parseOfxContent(multiOfxContent);
console.log(`   Account Statements Found: ${multiOfxParsed.accountStatements.length}`);
if (
  multiOfxParsed.accountStatements.length === 2 &&
  multiOfxParsed.accountStatements[0].accountNumber === 'ACCT_CHECKING_101' &&
  multiOfxParsed.accountStatements[0].transactions.length === 1 &&
  multiOfxParsed.accountStatements[1].accountNumber === 'ACCT_SAVINGS_202' &&
  multiOfxParsed.accountStatements[1].transactions.length === 1
) {
  console.log('✅ Multi-Account OFX parsing test passed!');
} else {
  console.error('❌ Multi-Account OFX parsing test failed!', JSON.stringify(multiOfxParsed, null, 2));
  process.exit(1);
}

// 4. Transaction Preview Formatting Test
console.log('\n🧪 Testing Transaction Preview Formatting...');
const sampleStmt = {
  accountNumber: '99887766',
  transactions: [
    { date: '2026-08-01', amount: -4520, payee_name: "Trader Joe's" },
    { date: '2026-08-02', amount: 150000, payee_name: "Payroll Deposit" },
    { date: '2026-08-03', amount: -1599, payee_name: "Streaming Subscription" },
    { date: '2026-08-04', amount: -2500, payee_name: "Gas Station" }
  ]
};

const previewOutput = formatTransactionPreview(sampleStmt, 'export_august.csv');
console.log(previewOutput);

if (
  previewOutput.includes('export_august.csv') &&
  previewOutput.includes('99887766') &&
  previewOutput.includes('Transactions: 4') &&
  previewOutput.includes('2026-08-01 to 2026-08-04') &&
  previewOutput.includes('$1413.81') &&
  previewOutput.includes("Trader Joe's") &&
  previewOutput.includes("Payroll Deposit")
) {
  console.log('\n✅ Transaction preview formatting test passed!');
} else {
  console.error('\n❌ Transaction preview formatting test failed!');
  process.exit(1);
}

// 5. Generic Filename & Date Stripping Test
console.log('\n🧪 Testing Generic Filename & Date Stripping...');
const { getFilenameBaseAndIsGeneric } = await import('./matcher.js');

const res1 = getFilenameBaseAndIsGeneric('2026-09-02_transaction_download (1).qif');
const res2 = getFilenameBaseAndIsGeneric('chase_checking_2026-09-02.csv');
const res3 = getFilenameBaseAndIsGeneric('20260902_statement.qfx');

console.log(`   "2026-09-02_transaction_download (1).qif" -> Base: "${res1.base}", Generic: ${res1.isGeneric}`);
console.log(`   "chase_checking_2026-09-02.csv" -> Base: "${res2.base}", Generic: ${res2.isGeneric}`);
console.log(`   "20260902_statement.qfx" -> Base: "${res3.base}", Generic: ${res3.isGeneric}`);

if (
  res1.isGeneric &&
  res1.base === 'transaction_download' &&
  !res2.isGeneric &&
  res2.base === 'chase_checking' &&
  res3.isGeneric &&
  res3.base === 'statement'
) {
  console.log('✅ Generic filename & date stripping tests passed!');
} else {
  console.error('❌ Generic filename & date stripping tests failed!', { res1, res2, res3 });
  process.exit(1);
}

// 6. Capital One 360 CSV Parsing Test
console.log('\n🧪 Testing Capital One 360 CSV Parsing (Payment & Deposit columns)...');
const capOneCsvContent = `Transaction Date,Posted Date,Card No.,Description,Category,Transaction Type,Payment,Deposit
2026-08-01,2026-08-01,1234,Trader Joe's,Groceries,Debit,45.50,
2026-08-02,2026-08-02,1234,Payroll Deposit,Income,Credit,,1250.00`;

const parsedCapOne = parseCsvContent(capOneCsvContent, 'capital_one_360.csv');
const capOneStmt = parsedCapOne.accountStatements[0];
console.log(`   Transaction Count: ${capOneStmt.transactions.length}`);
console.log(`   Tx 1 Amount: ${capOneStmt.transactions[0]?.amount} (expected -4550)`);
console.log(`   Tx 2 Amount: ${capOneStmt.transactions[1]?.amount} (expected 125000)`);

if (
  capOneStmt.transactions.length === 2 &&
  capOneStmt.transactions[0].amount === -4550 &&
  capOneStmt.transactions[1].amount === 125000 &&
  capOneStmt.detectedHeaders?.outflowHeader === 'Payment' &&
  capOneStmt.detectedHeaders?.inflowHeader === 'Deposit'
) {
  console.log('✅ Capital One 360 CSV parsing test passed!');
} else {
  console.error('❌ Capital One 360 CSV parsing test failed!', capOneStmt);
  process.exit(1);
}

// 7. Single Amount Column CSV Parsing Test
console.log('\n🧪 Testing Single Amount Column CSV Parsing...');
const singleAmtCsvContent = `Date,Description,Amount,Memo
2026-08-10,Coffee Shop,-4.75,Morning coffee
2026-08-11,Freelance Payment,500.00,Design work`;

const parsedSingleAmt = parseCsvContent(singleAmtCsvContent, 'single_amount.csv');
const singleAmtStmt = parsedSingleAmt.accountStatements[0];
console.log(`   Transaction Count: ${singleAmtStmt.transactions.length}`);
console.log(`   Tx 1 Amount: ${singleAmtStmt.transactions[0]?.amount} (expected -475)`);
console.log(`   Tx 2 Amount: ${singleAmtStmt.transactions[1]?.amount} (expected 50000)`);

if (
  singleAmtStmt.transactions.length === 2 &&
  singleAmtStmt.transactions[0].amount === -475 &&
  singleAmtStmt.transactions[1].amount === 50000 &&
  singleAmtStmt.detectedHeaders?.amountHeader === 'Amount'
) {
  console.log('✅ Single Amount column CSV parsing test passed!');
} else {
  console.error('❌ Single Amount column CSV parsing test failed!', singleAmtStmt);
  process.exit(1);
}

// 8. formatCsvMappingRundown Output Test
console.log('\n🧪 Testing formatCsvMappingRundown Output...');
const testProfile: CsvProfile = {
  dateHeader: 'TxDate',
  payeeHeader: 'PayeeName',
  outflowHeader: 'ExpenseAmt',
  inflowHeader: 'IncomeAmt',
  amountHeader: undefined,
  notesHeader: 'Remarks'
};
const rundownOutput = formatCsvMappingRundown(testProfile, 'test_statement.csv');
console.log(rundownOutput);

if (
  rundownOutput.includes('test_statement.csv') &&
  rundownOutput.includes('TxDate') &&
  rundownOutput.includes('PayeeName') &&
  rundownOutput.includes('ExpenseAmt') &&
  rundownOutput.includes('IncomeAmt') &&
  rundownOutput.includes('(None)') &&
  rundownOutput.includes('Remarks')
) {
  console.log('\n✅ formatCsvMappingRundown output test passed!');
} else {
  console.error('\n❌ formatCsvMappingRundown output test failed!');
  process.exit(1);
}

// 9. CSV Profile Mapping Overrides Test
console.log('\n🧪 Testing CSV Profile Mapping Overrides...');
const customCsvContent = `TxnDate,Merchant,DebitAmt,CreditAmt,Comments
2026-08-15,Supermarket,32.10,,Weekly groceries
2026-08-16,Refund,,15.00,Item return`;

const customProfile: CsvProfile = {
  dateHeader: 'TxnDate',
  payeeHeader: 'Merchant',
  outflowHeader: 'DebitAmt',
  inflowHeader: 'CreditAmt',
  notesHeader: 'Comments'
};

const parsedCustom = parseCsvContent(customCsvContent, 'custom.csv', customProfile);
const customStmt = parsedCustom.accountStatements[0];

if (
  customStmt.transactions.length === 2 &&
  customStmt.transactions[0].amount === -3210 &&
  customStmt.transactions[0].payee_name === 'Supermarket' &&
  customStmt.transactions[0].notes === 'Weekly groceries' &&
  customStmt.transactions[1].amount === 1500 &&
  customStmt.transactions[1].payee_name === 'Refund' &&
  customStmt.transactions[1].notes === 'Item return' &&
  customStmt.detectedHeaders?.dateHeader === 'TxnDate' &&
  customStmt.detectedHeaders?.payeeHeader === 'Merchant' &&
  customStmt.detectedHeaders?.outflowHeader === 'DebitAmt' &&
  customStmt.detectedHeaders?.inflowHeader === 'CreditAmt' &&
  customStmt.detectedHeaders?.notesHeader === 'Comments'
) {
  console.log('✅ CSV profile mapping overrides test passed!');
} else {
  console.error('❌ CSV profile mapping overrides test failed!', customStmt);
  process.exit(1);
}

// 10. Final Review Box Formatting Test
console.log("\n🧪 Testing Final Review Box Formatting...");
const reviewBoxCsv = formatFinalReviewBox({
  filename: "file.qif",
  accountName: "Savor Card [J]",
  isCsv: true,
  csvOutflowInflow: "Payment / Deposit",
  ruleToSave: "Match exact filename"
});
console.log(reviewBoxCsv);

if (
  reviewBoxCsv.includes('FINAL REVIEW FOR "file.qif"') &&
  reviewBoxCsv.includes("Selected Account: Savor Card [J]") &&
  reviewBoxCsv.includes("CSV Outflow/Inflow: Payment / Deposit") &&
  reviewBoxCsv.includes("Rule to Save: Match exact filename")
) {
  console.log("✅ Final Review Box formatting test passed!");
} else {
  console.error("❌ Final Review Box formatting test failed!");
  process.exit(1);
}

// 11. Rule to Save Description Helper Test
console.log("\n🧪 Testing Rule to Save Description Helper...");
const desc1 = getRuleToSaveDescription({
  statement: { transactions: [], accountNumber: "12345" },
  saveRule: true,
  isGeneric: false,
  filename: "chase.csv",
  filenameBase: "chase",
  genericMatchChoice: "exact"
});

const desc2 = getRuleToSaveDescription({
  statement: { transactions: [] },
  saveRule: true,
  isGeneric: true,
  filename: "2026_download.csv",
  filenameBase: "download",
  genericMatchChoice: "exact"
});

const desc3 = getRuleToSaveDescription({
  statement: { transactions: [] },
  saveRule: false,
  isGeneric: false,
  filename: "chase.csv",
  filenameBase: "chase",
  genericMatchChoice: "exact"
});

if (
  desc1 === "Match account number (12345)" &&
  desc2 === "Match exact filename" &&
  desc3 === "Do not save rule"
) {
  console.log("✅ Rule to Save description helper test passed!");
} else {
  console.error("❌ Rule to Save description helper test failed!", { desc1, desc2, desc3 });
  process.exit(1);
}

// 12. Wizard State Transitions & Go Back Navigation Test
console.log("\n🧪 Testing Wizard State Transitions & Go Back Navigation...");
const step1 = getNextWizardStep("CSV_MAPPING", "keep", { isCsv: true, isGeneric: false, saveRule: true, hasAccount: false });
const step2 = getNextWizardStep("ACCOUNT_SELECTION", "__GOBACK__", { isCsv: true, isGeneric: false, saveRule: true, hasAccount: false });
const step3 = getNextWizardStep("ACCOUNT_SELECTION", "select", { isCsv: true, isGeneric: true, saveRule: true, hasAccount: true });
const step4 = getNextWizardStep("GENERIC_RULE", "__GOBACK__", { isCsv: true, isGeneric: true, saveRule: true, hasAccount: true });
const step5 = getNextWizardStep("REVIEW", "edit_account", { isCsv: true, isGeneric: false, saveRule: true, hasAccount: true });
const step6 = getNextWizardStep("REVIEW", "edit_csv", { isCsv: true, isGeneric: false, saveRule: true, hasAccount: true });

console.log(`   CSV_MAPPING -> keep: ${step1} (expected ACCOUNT_SELECTION)`);
console.log(`   ACCOUNT_SELECTION -> __GOBACK__: ${step2} (expected CSV_MAPPING)`);
console.log(`   ACCOUNT_SELECTION -> select (generic): ${step3} (expected GENERIC_RULE)`);
console.log(`   GENERIC_RULE -> __GOBACK__: ${step4} (expected ACCOUNT_SELECTION)`);
console.log(`   REVIEW -> edit_account: ${step5} (expected ACCOUNT_SELECTION)`);
console.log(`   REVIEW -> edit_csv: ${step6} (expected CSV_MAPPING)`);

if (
  step1 === "ACCOUNT_SELECTION" &&
  step2 === "CSV_MAPPING" &&
  step3 === "GENERIC_RULE" &&
  step4 === "ACCOUNT_SELECTION" &&
  step5 === "ACCOUNT_SELECTION" &&
  step6 === "CSV_MAPPING"
) {
  console.log("✅ Wizard state transitions & Go Back navigation test passed!");
} else {
  console.error("❌ Wizard state transitions test failed!", { step1, step2, step3, step4, step5, step6 });
  process.exit(1);
}

// 13. Scalar Amount + Transaction Type Column CSV Parsing Test
console.log('\n🧪 Testing Scalar Amount + Transaction Type Column CSV Parsing...');
const scalarTypeCsvContent = `Date,Description,Amount,Transaction Type
2026-08-20,Grocery Store,50.00,Debit
2026-08-21,Paycheck,2000.00,Credit
2026-08-22,Online Refund,25.00,Refund
2026-08-23,ATM Withdrawal,100.00,Withdrawal`;

const parsedScalarType = parseCsvContent(scalarTypeCsvContent, 'scalar_type.csv');
const scalarTypeStmt = parsedScalarType.accountStatements[0];
console.log(`   Transaction Count: ${scalarTypeStmt.transactions.length}`);
console.log(`   Tx 1 Amount (Debit 50.00): ${scalarTypeStmt.transactions[0]?.amount} (expected -5000)`);
console.log(`   Tx 2 Amount (Credit 2000.00): ${scalarTypeStmt.transactions[1]?.amount} (expected 200000)`);
console.log(`   Tx 3 Amount (Refund 25.00): ${scalarTypeStmt.transactions[2]?.amount} (expected 2500)`);
console.log(`   Tx 4 Amount (Withdrawal 100.00): ${scalarTypeStmt.transactions[3]?.amount} (expected -10000)`);

if (
  scalarTypeStmt.transactions.length === 4 &&
  scalarTypeStmt.transactions[0].amount === -5000 &&
  scalarTypeStmt.transactions[1].amount === 200000 &&
  scalarTypeStmt.transactions[2].amount === 2500 &&
  scalarTypeStmt.transactions[3].amount === -10000 &&
  scalarTypeStmt.detectedHeaders?.amountHeader === 'Amount' &&
  scalarTypeStmt.detectedHeaders?.typeHeader === 'Transaction Type'
) {
  console.log('✅ Scalar Amount + Transaction Type column CSV parsing test passed!');
} else {
  console.error('❌ Scalar Amount + Transaction Type column CSV parsing test failed!', scalarTypeStmt);
  process.exit(1);
}

// 14. formatBatchSummaryTable Helper Test
console.log('\n🧪 Testing formatBatchSummaryTable Helper...');
const stagedSample: StagedImport[] = [
  {
    filePath: 'test-samples/sample_checking.ofx',
    filename: 'sample_checking.ofx',
    statement: {
      accountNumber: '112233',
      transactions: [
        { date: '2026-08-01', amount: -5000, payee_name: 'Store A' },
        { date: '2026-08-02', amount: 20000, payee_name: 'Deposit B' }
      ]
    },
    selectedAccount: { id: 'acc1', name: 'Checking Account' },
    action: 'import'
  },
  {
    filePath: 'test-samples/sample_credit.csv',
    filename: 'sample_credit.csv',
    statement: {
      accountNumber: undefined,
      transactions: [
        { date: '2026-08-05', amount: -4520, payee_name: 'Supermarket' }
      ]
    },
    selectedAccount: { id: 'acc2', name: 'Credit Card' },
    action: 'import'
  },
  {
    filePath: 'test-samples/skipped.qif',
    filename: 'skipped.qif',
    statement: {
      transactions: []
    },
    action: 'skip'
  }
];

const batchSummaryOutput = formatBatchSummaryTable(stagedSample);
console.log(batchSummaryOutput);

if (
  batchSummaryOutput.includes('File Name') &&
  batchSummaryOutput.includes('Account Name') &&
  batchSummaryOutput.includes('Transaction Count') &&
  batchSummaryOutput.includes('Date Range') &&
  batchSummaryOutput.includes('Net Flow') &&
  batchSummaryOutput.includes('sample_checking.ofx') &&
  batchSummaryOutput.includes('Checking Account') &&
  batchSummaryOutput.includes('2026-08-01 to 2026-08-02') &&
  batchSummaryOutput.includes('+$150.00') &&
  batchSummaryOutput.includes('sample_credit.csv') &&
  batchSummaryOutput.includes('Credit Card') &&
  batchSummaryOutput.includes('-$45.20') &&
  batchSummaryOutput.includes('skipped.qif') &&
  batchSummaryOutput.includes('(Skipped)')
) {
  console.log('✅ formatBatchSummaryTable helper test passed!');
} else {
  console.error('❌ formatBatchSummaryTable helper test failed!');
  process.exit(1);
}

// 15. Capital One 360 Extended Transaction Type & Stable imported_id Test
console.log('\n🧪 Testing Capital One 360 Extended Types & Stable imported_id...');
const extendedCapOneCsv = `Account Number,Transaction Date,Transaction Amount,Transaction Type,Transaction Description,Balance
9661,2026-08-20,501.00,CARD PURCHASE,STORE PURCHASE,1000.00
9661,2026-08-19,2000.00,DIRECT DEPOSIT,PAYROLL DIRECT DEPOSIT,1501.00
9661,2026-08-18,100.00,ATM WITHDRAWAL,ATM WITHDRAWAL,3501.00
9661,2026-08-17,429.72,WEBXFR,TRANSFER OUT,3601.00`;

const parsedExtended = parseCsvContent(extendedCapOneCsv, 'Checking...9661.csv');
const extStmt = parsedExtended.accountStatements[0];

if (
  extStmt.transactions.length === 4 &&
  extStmt.transactions[0].amount === -50100 &&
  extStmt.transactions[0].imported_id === '2026-08-20-0' &&
  extStmt.transactions[1].amount === 200000 &&
  extStmt.transactions[1].imported_id === '2026-08-19-1' &&
  extStmt.transactions[2].amount === -10000 &&
  extStmt.transactions[2].imported_id === '2026-08-18-2' &&
  extStmt.transactions[3].amount === -42972 &&
  extStmt.transactions[3].imported_id === '2026-08-17-3'
) {
  console.log('✅ Capital One 360 Extended Types & Stable imported_id test passed!');
} else {
  console.error('❌ Capital One 360 Extended Types test failed!', extStmt);
  process.exit(1);
}

// 16. Account Balances Table Formatting Test
console.log('\n🧪 Testing Account Balances Table Formatting...');
const { formatAccountBalancesTable, formatCurrencyCents } = await import('./balances.js');

const balanceSample = [
  {
    accountId: 'acc1',
    accountName: '360 Checking',
    currentBalanceCents: 150000,
    netFlowCents: -50000,
    projectedBalanceCents: 100000
  },
  {
    accountId: 'acc2',
    accountName: 'Joint Savings',
    currentBalanceCents: 500000,
    netFlowCents: 50000,
    projectedBalanceCents: 550000
  }
];

const balanceTableOutput = formatAccountBalancesTable(balanceSample);
console.log(balanceTableOutput);

if (
  balanceTableOutput.includes('360 Checking') &&
  balanceTableOutput.includes('$1500.00') &&
  balanceTableOutput.includes('-$500.00') &&
  balanceTableOutput.includes('$1000.00') &&
  balanceTableOutput.includes('Joint Savings') &&
  balanceTableOutput.includes('$5000.00') &&
  balanceTableOutput.includes('+$500.00') &&
  balanceTableOutput.includes('$5500.00')
) {
  console.log('✅ Account Balances Table Formatting test passed!');
} else {
  console.error('❌ Account Balances Table Formatting test failed!');
  process.exit(1);
}

// 17. Intra-Batch Paired Transfer Detection Test
console.log('\n🧪 Testing Intra-Batch Paired Transfer Detection...');
const { detectIntraBatchTransferPairs, formatTransferPairsSummary } = await import('./transferMatcher.js');

const transferStagedSample: StagedImport[] = [
  {
    filePath: 'checking.csv',
    filename: 'checking.csv',
    statement: {
      transactions: [
        { date: '2026-09-01', amount: -50000, payee_name: 'Online Transfer to Savings' }
      ]
    },
    selectedAccount: { id: 'acc_checking', name: 'Checking Account' },
    action: 'import'
  },
  {
    filePath: 'savings.csv',
    filename: 'savings.csv',
    statement: {
      transactions: [
        { date: '2026-09-03', amount: 50000, payee_name: 'Deposit from Checking' }
      ]
    },
    selectedAccount: { id: 'acc_savings', name: 'Savings Account' },
    action: 'import'
  }
];

const mockPayees = [
  { id: 'payee_trf_savings', name: 'Transfer: Savings Account', transfer_acct: 'acc_savings' },
  { id: 'payee_trf_checking', name: 'Transfer: Checking Account', transfer_acct: 'acc_checking' }
];

const detectedPairs = await detectIntraBatchTransferPairs(transferStagedSample, mockPayees, { maxDateDeltaDays: 5 });

console.log(formatTransferPairsSummary(detectedPairs));

if (
  detectedPairs.length === 1 &&
  detectedPairs[0].accountA.id === 'acc_checking' &&
  detectedPairs[0].accountB.id === 'acc_savings' &&
  detectedPairs[0].dateDeltaDays === 2 &&
  transferStagedSample[0].statement.transactions[0].payee === 'payee_trf_savings' &&
  transferStagedSample[1].statement.transactions[0].payee === 'payee_trf_checking'
) {
  console.log('✅ Intra-Batch Paired Transfer Detection test passed!');
} else {
  console.error('❌ Intra-Batch Paired Transfer Detection test failed!', detectedPairs, transferStagedSample);
  process.exit(1);
}

console.log('\n🎉 ALL TESTS PASSED SUCCESSFULLY!');

