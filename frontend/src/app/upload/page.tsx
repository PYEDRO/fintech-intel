"use client";
import { useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { Upload, FileSpreadsheet, CheckCircle2, XCircle, Loader2 } from "lucide-react";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type StageStatus = "idle" | "uploading" | "processing" | "done" | "error";

interface JobEvent {
  job_id?: string;
  status?: string;
  step_label?: string;
  step_index?: number;
  total_steps?: number;
  progress_pct?: number;
  result?: {
    total_rows: number;
    classified: number;
    indexed: number;
    metrics_summary: Record<string, unknown>;
  };
  error?: string;
}

const STEP_COLORS = [
  "bg-blue-500",
  "bg-blue-500",
  "bg-violet-500",
  "bg-indigo-500",
  "bg-emerald-500",
];

export default function UploadPage() {
  const router = useRouter();
  const [stage, setStage] = useState<StageStatus>("idle");
  const [fileName, setFileName] = useState("");
  const [job, setJob] = useState<JobEvent>({});
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const stopSSE = () => {
    esRef.current?.close();
    esRef.current = null;
  };

  const startSSE = (jobId: string) => {
    stopSSE();
    const es = new EventSource(`${BASE_URL}/api/upload/progress/${jobId}`);
    esRef.current = es;

    es.onmessage = (e) => {
      const data: JobEvent = JSON.parse(e.data);
      setJob(data);

      if (data.status === "completed") {
        setStage("done");
        stopSSE();
      } else if (data.status === "failed") {
        setError(data.error ?? "Falha no processamento");
        setStage("error");
        stopSSE();
      }
    };

    es.onerror = () => {
      setError("Conexão SSE interrompida");
      setStage("error");
      stopSSE();
    };
  };

  const processFile = useCallback(async (file: File) => {
    setFileName(file.name);
    setStage("uploading");
    setError("");
    setJob({});

    const form = new FormData();
    form.append("file", file);

    try {
      const res = await fetch(`${BASE_URL}/api/upload`, { method: "POST", body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? "Upload failed");
      }
      const { job_id } = await res.json();
      setStage("processing");
      startSSE(job_id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro desconhecido");
      setStage("error");
    }
  }, []);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) processFile(file);
  };

  const pct = job.progress_pct ?? 0;
  const stepIdx = job.step_index ?? 0;
  const totalSteps = job.total_steps ?? 5;

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Upload de Dados</h1>
      <p className="text-sm text-gray-500 mb-6">
        Envie um arquivo XLSX ou CSV — o processamento ocorre em background com progresso em tempo real
      </p>

      {/* Drop zone */}
      {(stage === "idle" || stage === "error") && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => document.getElementById("file-input")?.click()}
          className={`border-2 border-dashed rounded-2xl p-12 text-center transition-all cursor-pointer
            ${dragOver ? "border-blue-400 bg-blue-50" : "border-gray-200 hover:border-blue-300 hover:bg-gray-50"}`}
        >
          <input
            id="file-input"
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) processFile(f); }}
            className="hidden"
          />
          <Upload className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-600 font-medium">Arraste o arquivo aqui ou clique para selecionar</p>
          <p className="text-sm text-gray-400 mt-1">Suporta .xlsx e .csv</p>
          <p className="text-xs text-gray-300 mt-3">Colunas: id, valor, data, status, cliente, descricao</p>
        </div>
      )}

      {/* Processing — SSE progress */}
      {(stage === "uploading" || stage === "processing") && (
        <div className="bg-white border border-gray-100 rounded-2xl p-8 shadow-sm">
          <div className="flex items-center gap-3 mb-6">
            <Loader2 className="w-6 h-6 text-blue-500 animate-spin flex-shrink-0" />
            <div>
              <p className="font-semibold text-gray-800">
                {stage === "uploading" ? "Enviando arquivo..." : (job.step_label ?? "Inicializando...")}
              </p>
              <p className="text-xs text-gray-400 mt-0.5">{fileName}</p>
            </div>
          </div>

          {/* Progress bar */}
          <div className="mb-4">
            <div className="flex justify-between text-xs text-gray-500 mb-1">
              <span>Etapa {stepIdx} de {totalSteps}</span>
              <span>{pct}%</span>
            </div>
            <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${STEP_COLORS[stepIdx] ?? "bg-blue-500"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>

          {/* Step indicators */}
          <div className="flex gap-1.5 flex-wrap">
            {Array.from({ length: totalSteps }, (_, i) => (
              <div
                key={i}
                className={`h-1 flex-1 rounded-full transition-all duration-300 ${
                  i < stepIdx ? "bg-emerald-400" : i === stepIdx ? "bg-blue-500 animate-pulse" : "bg-gray-100"
                }`}
              />
            ))}
          </div>
          <p className="text-center text-xs text-gray-400 mt-4">
            Não feche esta página durante o processamento
          </p>
        </div>
      )}

      {/* Error */}
      {stage === "error" && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-xl flex items-start gap-3">
          <XCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-medium text-red-700">Erro ao processar arquivo</p>
            <p className="text-sm text-red-600 mt-1">{error}</p>
            <button
              onClick={() => setStage("idle")}
              className="mt-2 text-xs text-red-500 underline"
            >
              Tentar novamente
            </button>
          </div>
        </div>
      )}

      {/* Success */}
      {stage === "done" && job.result && (
        <div className="space-y-4">
          <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-6 flex items-center gap-4">
            <CheckCircle2 className="w-8 h-8 text-emerald-500 flex-shrink-0" />
            <div>
              <p className="font-semibold text-emerald-800">Processamento concluído!</p>
              <p className="text-sm text-emerald-600 mt-0.5">{fileName}</p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Linhas processadas", value: job.result.total_rows.toLocaleString("pt-BR") },
              { label: "Classificadas (IA)", value: job.result.classified.toLocaleString("pt-BR") },
              { label: "Vetores indexados", value: job.result.indexed.toLocaleString("pt-BR") },
            ].map(({ label, value }) => (
              <div key={label} className="bg-white border border-gray-100 rounded-xl p-4 text-center shadow-sm">
                <p className="text-2xl font-bold text-gray-900">{value}</p>
                <p className="text-xs text-gray-500 mt-1">{label}</p>
              </div>
            ))}
          </div>

          <div className="bg-white border border-gray-100 rounded-xl p-5 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
              <FileSpreadsheet className="w-4 h-4 text-blue-500" />
              Resumo dos dados
            </h3>
            <pre className="text-xs text-gray-600 bg-gray-50 rounded-lg p-3 overflow-x-auto">
              {JSON.stringify(job.result.metrics_summary, null, 2)}
            </pre>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => { setStage("idle"); setJob({}); }}
              className="flex-1 border border-gray-200 text-gray-700 rounded-xl py-3 font-medium hover:bg-gray-50 transition-colors"
            >
              Novo upload
            </button>
            <button
              onClick={() => router.push("/")}
              className="flex-1 bg-blue-600 text-white rounded-xl py-3 font-medium hover:bg-blue-700 transition-colors"
            >
              Ver Dashboard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
