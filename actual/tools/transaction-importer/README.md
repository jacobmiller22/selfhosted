# Transaction Importer Tool 💳

A CLI tool for importing bank statement transaction files (`.csv`, `.ofx`, `.qfx`, `.qbo`, `.qif`) into a self-hosted [Actual Budget](https://actualbudget.org/) server.

## Features

- 📱 **Mobile Screenshot Vision Extraction**: Extracts transactions directly from mobile banking screenshots (`.png`, `.jpg`, `.jpeg`, `.webp`, `.heic`) using Google Gemini Flash Multimodal structured outputs (`responseSchema`).
- 📂 **Multi-format Statement Support**: Parses `.csv`, `.ofx`, `.qfx`, `.qbo`, and `.qif` statement files.
- 🎯 **Automated Account Matching**: Detects matching Actual Budget accounts via bank account numbers (`<ACCTID>`, `!Account`, card last 4 digits `6341`), account aliases (`checking`, `savings`), or saved rules.
- 📅 **Relative Date Resolution**: Deterministically normalizes relative dates (`Today`, `Yesterday`, days of the week, short dates) relative to reference anchor dates.
- 💬 **Interactive Fallback**: Prompts interactively to select an account if auto-detection is unsure, with option to save learned rules.
- 🔄 **Reconciliation & Deduplication**: Utilizes deterministic transaction fingerprinting (`imported_id`) and Actual Budget's native `importTransactions` API for automated deduplication and rule application.
- 📦 **Post-Processing Archive**: Automatically moves imported statement files and screenshots into an `archived/` subfolder.

## Usage

```bash
# Run against a directory containing downloaded transaction statements or screenshots:
npm run import -- /path/to/downloads

# Process a single mobile banking screenshot:
npm run import -- /path/to/screenshot.png

# Perform a dry run without pushing changes to Actual Budget:
npm run import -- /path/to/downloads --dry-run
```

## Testing & Evaluation

```bash
# Run all tests (statement parsers + vision extraction engine):
npm test

# Run vision unit & golden sample evaluation tests only:
npm run test:vision

# Run statement parser tests only:
npm run test:parsers
```
