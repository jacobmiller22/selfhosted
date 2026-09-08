# Transaction Importer Tool 💳

A CLI tool for importing bank statement transaction files (`.csv`, `.ofx`, `.qfx`, `.qbo`, `.qif`) into a self-hosted [Actual Budget](https://actualbudget.org/) server.

## Features

- 📂 **Multi-format Support**: Parses `.csv`, `.ofx`, `.qfx`, `.qbo`, and `.qif` statement files.
- 🎯 **Automated Account Matching**: Detects matching Actual Budget accounts via bank account numbers (`<ACCTID>` or `!Account`) or saved file rules.
- 💬 **Interactive Fallback**: Prompts interactively to select an account if auto-detection is unsure, with option to save learned rules.
- 🔄 **Reconciliation & Deduplication**: Utilizes Actual Budget's native `importTransactions` API for automated deduplication and rule application.
- 📦 **Post-Processing Archive**: Automatically moves imported statement files into an `archived/` subfolder.

## Usage

```bash
# Run against a directory containing downloaded transaction statements:
npm run import -- /path/to/downloads

# Perform a dry run without pushing changes to Actual Budget:
npm run import -- /path/to/downloads --dry-run
```
