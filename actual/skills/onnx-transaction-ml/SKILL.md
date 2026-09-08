---
name: onnx-transaction-ml
description: Comprehensive Machine Learning student guide covering feature engineering, TF-IDF, multi-class logistic regression, ONNX compilation, and production memory optimization for financial transaction classification.
---

# ONNX Transaction Machine Learning Skill
*Written from the perspective of an ML Student & Systems Engineer*

This skill documents the theoretical foundations, feature engineering mathematics, model training pipelines, ONNX compilation graphs, and runtime memory optimization strategies implemented in the Actual Budget ML Auto-Categorizer.

---

## 1. Problem Formulation

Financial transaction classification on personal ledgers involves two supervised multi-class prediction tasks on noisy, unformatted bank strings:

1. **Category Classification**: Map a transaction vector $\mathbf{x}$ to a target budget category UUID $y_{\text{cat}} \in \mathcal{C}$, where $|\mathcal{C}| = K$ (e.g., $K = 48$ user-defined budget categories like *Groceries*, *Housing*, *Income [J]*, *Bills*).
2. **Payee Resolution**: Map a transaction vector $\mathbf{x}$ to a canonical payee UUID $y_{\text{payee}} \in \mathcal{P}$ (e.g., *Trader Joe's*, *Rocket Mortgage*, *Capital One*).

---

## 2. Feature Engineering & Mathematical Representations

Raw transaction records contain unstructured text (`imported_payee`), numerical dollar amounts (`amount`), account identifiers (`account_id`), and ISO date strings (`date`).

```
Raw Entry: "TRADER JOE'S #521 SAN FRANCISCO CA" | Amount: -$45.20 | Account: "acct_checking" | Date: "2026-09-08"
```

### A. Text Preprocessing & Tokenization
Bank strings contain trailing store numbers, timestamps, and punctuation. The text cleaner applies regex string normalization:

$$\text{clean}(s) = \text{strip\_special\_chars}(\text{lowercase}(s))$$

Example: `"TRADER JOE'S #521 SAN FRANCISCO"` $\rightarrow$ `"trader joes 521 san francisco"`

### B. Term Frequency-Inverse Document Frequency (TF-IDF)
To extract numerical representations from cleaned transaction strings, we apply TF-IDF vectorization over unigrams and bigrams (`ngram_range=(1, 2)`):

$$\text{TF-IDF}(t, d, D) = \text{TF}(t, d) \times \text{IDF}(t, D)$$

Where:
- **Sublinear Term Frequency**: Dampens the effect of repetitive words:
  $$\text{TF}(t, d) = 1 + \ln(\text{count}(t, d)) \quad \text{for count} > 0$$
- **Inverse Document Frequency**: Penalizes generic terms common across many payees:
  $$\text{IDF}(t, D) = \ln \left( \frac{1 + |D|}{1 + |\{d \in D : t \in d\}|} \right) + 1$$

### C. Logarithmic Amount Transformation
Transaction amounts span multiple orders of magnitude (from $\$0.50$ coffee to $\$50,000.00$ home deposits). To prevent large dollar values from dominating linear decision boundaries, we apply a log-1p transform paired with an explicit direction sign:

$$\text{amount\_log} = \ln(1 + |\text{amount\_cents}|)$$

$$\text{amount\_sign} = \begin{cases} +1.0 & \text{if } \text{amount\_cents} \ge 0 \\ -1.0 & \text{if } \text{amount\_cents} < 0 \end{cases}$$

### D. Cyclical Temporal Features
Date strings are decomposed into calendar sub-components to capture recurring monthly/weekly spending cycles (e.g., mortgage due on 1st of month, payroll on Fridays):
- **Day of Week**: $d_w \in \{0, \dots, 6\}$ (Monday=0, Sunday=6)
- **Day of Month**: $d_m \in \{1, \dots, 31\}$
- **Month**: $m \in \{1, \dots, 12\}$

### E. Categorical One-Hot Encoding
`account_id` strings are transformed using a sparse binary indicator vector with `handle_unknown="ignore"` to safely handle newly added bank accounts in inference.

---

## 3. Model Architecture & Loss Optimization

### Multi-Class Logistic Regression (Softmax Regression)
For a feature vector $\mathbf{x} \in \mathbb{R}^D$, the probability that transaction $i$ belongs to category class $k \in \{1, \dots, K\}$ is parameterized by weight matrix $W \in \mathbb{R}^{K \times D}$ and bias $\mathbf{b} \in \mathbb{R}^K$:

$$P(y_i = k \mid \mathbf{x}_i) = \frac{\exp(W_k^T \mathbf{x}_i + b_k)}{\sum_{j=1}^{K} \exp(W_j^T \mathbf{x}_i + b_j)}$$

### Class Weighting for Budget Imbalance
Personal budget data exhibits extreme class imbalance (e.g., hundreds of *Grocery* transactions vs. 12 *Property Tax* transactions per year). To prevent the model from collapsing into majority classes, we apply balanced sample weighting $w_k$:

$$w_k = \frac{N}{K \cdot N_k}$$

Where $N$ is total training samples and $N_k$ is the sample count for class $k$.

### Objective Function with $L_2$ Regularization
The objective function minimizes class-weighted cross-entropy loss with an $L_2$ penalty ($C = 10.0$):

$$\mathcal{L}(W, \mathbf{b}) = -\frac{1}{N} \sum_{i=1}^{N} \sum_{k=1}^{K} w_k \cdot \mathbb{I}(y_i = k) \log P(y_i = k \mid \mathbf{x}_i) + \frac{1}{2C} \|W\|_F^2$$

---

## 4. Train-Validation-Refit Strategy

1. **Stratified Splitting with Rare Class Handling**:
   - Split dataset 80% train / 20% validation.
   - If a class has fewer than 2 total samples ($N_k < 2$), stratification is dynamically disabled to prevent `ValueError: The least populated class in y has only 1 member`.
2. **Out-of-Sample Evaluation**:
   - Validation accuracy is logged during training (achieved **70.92% accuracy** on user's category dataset).
3. **Full Dataset Refitting**:
   - After computing validation metrics, `pipeline.fit(X, y)` is executed on **100% of available historical data**.
   - **ML Rationale**: Refitting on the complete dataset ensures that 100% of category UUIDs and payee vocabularies are incorporated into the final exported weight matrices.

---

## 5. ONNX Graph Compilation & Runtime Optimization

```
Scikit-Learn Pipeline (Python)  --->  skl2onnx Compiler  --->  .onnx Model Artifact  --->  onnxruntime-node (TypeScript)
```

### A. Graph Conversion & `zipmap=False`
Scikit-Learn pipelines are converted to ONNX graphs using `skl2onnx` (`target_opset=15`).
- **Critical Option**: `options = {LogisticRegression: {"zipmap": False}}`
- **Why `zipmap=False` Matters**: By default, ONNX exports probabilities as a `Sequence<Map<String, Float>>`. Disabling ZipMap forces ONNX Runtime to output a dense 2D float tensor `[N, K]`. This eliminates JavaScript object creation overhead in Node.js during inference.

### B. POSIX Locale Enforcement for `StringNormalizer`
ONNX's `StringNormalizer` operator uses C++ ICU unicode libraries for text normalization.
- **Docker Requirement**: The Docker container must install `locales` / `locales-all` and export environment variables:
  ```dockerfile
  ENV LANG=en_US.UTF-8
  ENV LC_ALL=en_US.UTF-8
  ```
  Without UTF-8 locale variables set, `onnxruntime-node` throws an unhandled C++ exception when instantiating the inference session.

---

## 6. Production Memory Management (Micro-Batching)

### C++ Native Tensor Accumulation
In `onnxruntime-node`, `InferenceSession.run(feeds)` allocates output tensors in native C++ heap memory outside the Node.js V8 garbage-collected heap.

- **Failure Scenario**: Running ML inference on 400+ transactions sequentially in a single synchronous loop allocates $400 \times 2 \times 4 = 3,200+$ native C++ tensors. The accumulation of un-freed native memory triggers container OOM SIGKILL (exit code 137).

### Solution: Micro-Batch Slicing
The sidecar daemon caps uncategorized transactions processed per cron run using `BATCH_SIZE=50`:

```typescript
const BATCH_SIZE = parseInt(process.env.BATCH_SIZE || "50", 10);

const allUncategorized = transactions.filter(
  (t) => !t.category && !t.transfer_id && !t.is_parent && !t.is_child
);
const uncategorizedTxs = allUncategorized.slice(0, BATCH_SIZE);
```

- **Result**: Each 15-minute cron cycle processes up to 50 transactions, keeping native C++ memory footprint tiny while systematically categorizing hundreds of historical transactions over time.

---

## 7. Python Training & Export Commands

To retrain and re-export ONNX models using Poetry:

```bash
# 1. Export historical dataset from Actual Budget
ssh bjorn "docker exec actual-auto-categorizer node dist/export_data.js"

# 2. Run Python training & ONNX export pipeline
cd actual/tools/auto-categorizer/python
poetry run python export_onnx.py

# 3. Copy generated models to root models directory
cp models/payee_resolver.onnx models/category_classifier.onnx models/model_manifest.json ../../../auto-categorizer-models/
```
