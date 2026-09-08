import fs from "fs";
import path from "path";
import * as ort from "onnxruntime-node";
import { cleanPayeeText } from "./textCleaner.js";

export interface ModelManifest {
  timestamp: string;
  models: {
    payee_resolver: {
      file: string;
      classes: string[];
    };
    category_classifier: {
      file: string;
      classes: string[];
    };
  };
}

export interface PredictionResult {
  label: string;
  confidence: number;
  probabilities: Record<string, number>;
}

export class OnnxPredictorEngine {
  private payeeSession: ort.InferenceSession | null = null;
  private categorySession: ort.InferenceSession | null = null;
  private manifest: ModelManifest | null = null;
  private modelsDir: string;

  constructor(modelsDir?: string) {
    this.modelsDir = modelsDir || path.resolve(process.cwd(), "src/models");
  }

  public async init(): Promise<void> {
    const manifestPath = path.join(this.modelsDir, "model_manifest.json");
    if (!fs.existsSync(manifestPath)) {
      throw new Error(`Model manifest not found at ${manifestPath}. Ensure models are deployed.`);
    }

    const manifestRaw = fs.readFileSync(manifestPath, "utf-8");
    this.manifest = JSON.parse(manifestRaw) as ModelManifest;

    const payeeModelPath = path.join(this.modelsDir, this.manifest.models.payee_resolver.file);
    const categoryModelPath = path.join(this.modelsDir, this.manifest.models.category_classifier.file);

    this.payeeSession = await ort.InferenceSession.create(payeeModelPath);
    this.categorySession = await ort.InferenceSession.create(categoryModelPath);

    console.log(`✓ Loaded ONNX sessions from ${this.modelsDir}`);
  }

  public async predictPayee(
    rawPayee: string,
    accountId: string,
    amountCents: number
  ): Promise<PredictionResult> {
    if (!this.payeeSession || !this.manifest) {
      throw new Error("Payee ONNX session not initialized. Call init() first.");
    }

    const cleanText = cleanPayeeText(rawPayee);
    const amountLog = Math.log1p(Math.abs(amountCents));
    const amountSign = amountCents >= 0 ? 1.0 : -1.0;

    const feeds: Record<string, ort.Tensor> = {
      cleaned_payee: new ort.Tensor("string", [cleanText], [1, 1]),
      account_id: new ort.Tensor("string", [accountId], [1, 1]),
      amount_log: new ort.Tensor("float32", new Float32Array([amountLog]), [1, 1]),
      amount_sign: new ort.Tensor("float32", new Float32Array([amountSign]), [1, 1])
    };

    const results = await this.payeeSession.run(feeds);
    
    const labelTensor = results.label || results[Object.keys(results)[0]];
    const probaTensor = results.probabilities || results[Object.keys(results)[1]];

    const predictedLabel = String((labelTensor.data as any)[0]);
    const probaArray = probaTensor.data as Float32Array;
    const classes = this.manifest.models.payee_resolver.classes;
    const probabilities: Record<string, number> = {};

    for (let i = 0; i < classes.length; i++) {
      if (i < probaArray.length) {
        probabilities[classes[i]] = Number(probaArray[i]);
      }
    }

    const confidence = probabilities[predictedLabel] ?? 1.0;

    return {
      label: predictedLabel,
      confidence,
      probabilities
    };
  }

  public async predictCategory(
    rawPayee: string,
    accountId: string,
    amountCents: number,
    dateStr: string
  ): Promise<PredictionResult> {
    if (!this.categorySession || !this.manifest) {
      throw new Error("Category ONNX session not initialized. Call init() first.");
    }

    const cleanText = cleanPayeeText(rawPayee);
    const amountLog = Math.log1p(Math.abs(amountCents));
    const amountSign = amountCents >= 0 ? 1.0 : -1.0;

    const dt = new Date(dateStr);
    const dayOfWeek = isNaN(dt.getTime()) ? 0 : (dt.getDay() + 6) % 7; // 0=Mon, 6=Sun
    const dayOfMonth = isNaN(dt.getTime()) ? 1 : dt.getDate();
    const month = isNaN(dt.getTime()) ? 1 : dt.getMonth() + 1;

    const feeds: Record<string, ort.Tensor> = {
      cleaned_payee: new ort.Tensor("string", [cleanText], [1, 1]),
      account_id: new ort.Tensor("string", [accountId], [1, 1]),
      amount_log: new ort.Tensor("float32", new Float32Array([amountLog]), [1, 1]),
      amount_sign: new ort.Tensor("float32", new Float32Array([amountSign]), [1, 1]),
      day_of_week: new ort.Tensor("float32", new Float32Array([dayOfWeek]), [1, 1]),
      day_of_month: new ort.Tensor("float32", new Float32Array([dayOfMonth]), [1, 1]),
      month: new ort.Tensor("float32", new Float32Array([month]), [1, 1])
    };

    const results = await this.categorySession.run(feeds);

    const labelTensor = results.label || results[Object.keys(results)[0]];
    const probaTensor = results.probabilities || results[Object.keys(results)[1]];

    const predictedLabel = String((labelTensor.data as any)[0]);
    const probaArray = probaTensor.data as Float32Array;
    const classes = this.manifest.models.category_classifier.classes;
    const probabilities: Record<string, number> = {};

    for (let i = 0; i < classes.length; i++) {
      if (i < probaArray.length) {
        probabilities[classes[i]] = Number(probaArray[i]);
      }
    }

    const confidence = probabilities[predictedLabel] ?? 1.0;

    return {
      label: predictedLabel,
      confidence,
      probabilities
    };
  }
}
