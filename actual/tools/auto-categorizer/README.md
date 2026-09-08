# Actual Budget ML Auto-Categorizer (`tools/auto-categorizer`)

An intelligent machine learning transaction categorization, payee normalization, and transfer detection tool for [Actual Budget](https://actualbudget.org/).

## Project Structure

- `python/`: Local Python model training, evaluation, ONNX serialization, and model deployment engine.
- `src/`: TypeScript / Node.js background sidecar daemon using `onnxruntime-node` and `@actual-app/api` to automatically categorize new transactions on your Actual Budget server.

## Quick Start (Python Local Model Training)

1. Navigate to the python directory:
   ```bash
   cd tools/auto-categorizer/python
   ```
2. Set up virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Configure environment variables in `.env`:
   ```env
   ACTUAL_SERVER_URL=http://localhost:5006
   ACTUAL_PASSWORD=your_password
   ACTUAL_SYNC_ID=your_sync_id
   ```
4. Fetch historical dataset, train models, and export ONNX graphs:
   ```bash
   python fetch_data.py
   python train.py
   python export_onnx.py
   ```
