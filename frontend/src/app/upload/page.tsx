"use client";
import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Upload, FileSpreadsheet, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { api, type UploadResponse } from "@/lib/api";

type State = "idle" | "loading" | "success" | "error";

export default function UploadPage() {
  const router = useRouter();
  const [state, setState] = useState<State>("idle");
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string>("");
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState<string>("");

  const processFile = async (file: File) => {
    setFileName(file.name);
    setState("loading");
    setError("");
    try {
      const data = await api.upload(file);
      setResult(data);
      setState("success");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro ao processar arquivo");
      setState("error");
    }
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) processFile(file);
  }, []);

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
  };

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Upload de Dados</h1>
      <p className="text-sm text-gray-500 mb-6">
        Envie um arquivo XLSX ou CSV com as transações financeiras para processar
      </p>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-2xl p-12 text-center transition-all cursor-pointer
          ${dragOver ? "border-blue-400 bg-blue-50" : "border-gray-200 hover:border-blue-300 hover:bg-gray-50"}
          ${state === "loading" ? "pointer-events-none opacity-60" : ""}
        `}
        onClick={() => document.getElementById("file-input")?.click()}
      >
        <input
          id="file-input"
          type="file"
          accept=".xlsx,.xls,.csv"
          onChange={onFileChange}
          className="hidden"
        />

        {state === "idle" || state === "error" ? (
          <>
            <Upload className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-600 font-medium">Arraste o arquivo aqui ou clique para selecionar</p>
            <p className="text-sm text-gray-400 mt-1">Suporta .xlsx e .csv</p>
            <p className="text-xs text-gray-300 mt-3">
              Colunas esperadas: id, valor, data, status, cliente, descricao
            </p>
          </>
        ) : state === "loading" ? (
          <>
            <Loader2 className="w-12 h-12 text-blue-500 mx-auto mb-3 animate-spin" />
            <p className="text-gray-700 font-medium">Processando {fileName}…</p>
            <p className="text-sm text-gray-400 mt-1">
              Limpando dados → classificando → indexando vetores
            </p>
          </>
        ) : (
          <>
            <CheckCircle2 className="w-12 h-12 text-emerald-500 mx-auto mb-3" />
            <p className="text-emerald-700 font-medium">Arquivo processado com sucesso!</p>
            <p className="text-sm text-gray-400 mt-1">{fileName}</p>
          </>
        )}
      </div>

      {/* Error */}
      {state === "error" && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-xl flex items-start gap-3">
          <XCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-medium text-red-700">Erro ao processar arquivo</p>
            <p className="text-sm text-red-600 mt-1">{error}</p>
          </div>
        </div>
      )}

      {/* Success summary */}
      {state === "success" && result && (
        <div className="mt-6 space-y-4">
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Linhas processadas", value: result.total_rows.toLocaleString("pt-BR") },
              { label: "Classificadas (IA)", value: result.classified.toLocaleString("pt-BR") },
              { label: "Vetores indexados", value: result.indexed.toLocaleString("pt-BR") },
            ].map(({ label, value }) => (
              <div key={label} className="bg-white border border-gray-100 rounded-xl p-4 text-center shadow-sm">
                <p className="text-2xl font-bold text-gray-900">{value}</p>
                <p className="text-xs text-gray-500 mt-1">{label}</p>
              </div>
            ))}
          </div>

          {/* Metrics preview */}
          <div className="bg-white border border-gray-100 rounded-xl p-5 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
              <FileSpreadsheet className="w-4 h-4 text-blue-500" />
              Resumo dos dados
            </h3>
            <pre className="text-xs text-gray-600 bg-gray-50 rounded-lg p-3 overflow-x-auto">
              {JSON.stringify(result.metrics_summary, null, 2)}
            </pre>
          </div>

          <button
            onClick={() => router.push("/")}
            className="w-full bg-blue-600 text-white rounded-xl py-3 font-medium hover:bg-blue-700 transition-colors"
          >
            Ver Dashboard
          </button>
        </div>
      )}
    </div>
  );
}
