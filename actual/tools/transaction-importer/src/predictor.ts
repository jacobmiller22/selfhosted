import fs from "fs";
import path from "path";

export interface PredictionResult {
  label: string;
  confidence: number;
  probabilities: Record<string, number>;
}

export interface ModelManifest {
  timestamp: string;
  models: {
    payee_resolver?: {
      file: string;
      classes: string[];
    };
  };
}

export function cleanPayeeText(text: string | null | undefined): string {
  if (!text || typeof text !== "string") {
    return "";
  }
  let cleaned = text.toLowerCase().trim();
  const prefixes = [
    /^sq\s*\*\s*/i,
    /^tst\s*\*\s*/i,
    /^paypal\s*\*\s*/i,
    /^py\s*\*\s*/i,
    /^sp\s*\*\s*/i,
    /^chk\s*card\s*/i,
    /^debit\s*card\s*purchase\s*/i,
    /^pos\s*purchase\s*/i,
    /^recurring\s*payment\s*/i,
    /^ach\s*withdrawal\s*/i,
    /^direct\s*deposit\s*/i
  ];
  for (const pat of prefixes) {
    cleaned = cleaned.replace(pat, "");
  }
  cleaned = cleaned.replace(/[^\w\s]/g, " ").replace(/\s+/g, " ").trim();
  return cleaned || text.toLowerCase().trim();
}

export class OnnxPredictorEngine {
  private payeeSession: any = null;
  private manifest: ModelManifest | null = null;
  private initialized = false;

  public async init(): Promise<boolean> {
    const candidateDirs = [
      process.env.MODELS_DIR,
      path.resolve(process.cwd(), "../auto-categorizer-models"),
      path.resolve(process.cwd(), "auto-categorizer-models"),
      path.resolve(process.cwd(), "src/models")
    ].filter(Boolean) as string[];

    let modelsDir: string | null = null;
    for (const dir of candidateDirs) {
      if (fs.existsSync(path.join(dir, "model_manifest.json"))) {
        modelsDir = dir;
        break;
      }
    }

    if (!modelsDir) {
      return false;
    }

    try {
      const manifestPath = path.join(modelsDir, "model_manifest.json");
      const manifestRaw = fs.readFileSync(manifestPath, "utf-8");
      this.manifest = JSON.parse(manifestRaw) as ModelManifest;

      if (!this.manifest.models.payee_resolver) {
        return false;
      }

      const payeeModelPath = path.join(modelsDir, this.manifest.models.payee_resolver.file);
      if (!fs.existsSync(payeeModelPath)) {
        return false;
      }

      // Dynamically import onnxruntime-node
      // @ts-ignore
      const ort = await import("onnxruntime-node");
      this.payeeSession = await ort.InferenceSession.create(payeeModelPath);
      this.initialized = true;
      return true;
    } catch {
      this.initialized = false;
      return false;
    }
  }

  public isInitialized(): boolean {
    return this.initialized;
  }

  public async predictPayee(
    rawPayee: string,
    accountId: string,
    amountCents: number
  ): Promise<PredictionResult | null> {
    if (!this.initialized || !this.payeeSession || !this.manifest?.models.payee_resolver) {
      return null;
    }

    try {
      // @ts-ignore
      const ort = await import("onnxruntime-node");
      const cleanText = cleanPayeeText(rawPayee);
      const amountLog = Math.log1p(Math.abs(amountCents));
      const amountSign = amountCents >= 0 ? 1.0 : -1.0;

      const feeds: Record<string, any> = {
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
    } catch {
      return null;
    }
  }
}
