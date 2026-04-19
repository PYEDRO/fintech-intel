"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Bot, User, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { api, type ChatSource } from "@/lib/api";

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
  streaming?: boolean;   // true enquanto tokens ainda estão chegando
  error?: boolean;
}

const SUGGESTIONS = [
  "Quais transações estão atrasadas?",
  "Qual cliente tem maior inadimplência?",
  "Quais itens são referentes a contratação?",
  "Qual é a receita total do período?",
];

// ── Componente de fontes colapsáveis ─────────────────────────────────────────

function SourcesCard({ sources }: { sources: ChatSource[] }) {
  const [open, setOpen] = useState(false);
  if (!sources.length) return null;
  return (
    <div className="mt-2 border border-gray-200 rounded-lg overflow-hidden text-xs">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <span className="font-medium text-gray-600">
          {sources.length} fonte{sources.length !== 1 ? "s" : ""} consultada{sources.length !== 1 ? "s" : ""}
        </span>
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
      {open && (
        <div className="divide-y divide-gray-100 max-h-40 overflow-y-auto">
          {sources.map((s) => (
            <div key={s.id} className="px-3 py-2 flex justify-between gap-3">
              <div>
                <span className="font-mono text-gray-500">{s.id}</span>
                <span className="mx-1 text-gray-300">·</span>
                <span className="text-gray-600 truncate">{s.descricao}</span>
              </div>
              <span className="text-gray-400 whitespace-nowrap">
                {(s.relevance * 100).toFixed(0)}% rel.
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Indicador de digitação (enquanto streaming) ───────────────────────────────

function TypingDots() {
  return (
    <span className="inline-flex gap-1 ml-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  );
}

// ── Componente principal ──────────────────────────────────────────────────────

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const nextIdRef = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const addMessage = useCallback((msg: Omit<Message, "id">): number => {
    const id = ++nextIdRef.current;
    setMessages((m) => [...m, { ...msg, id }]);
    return id;
  }, []);

  const updateMessage = useCallback((id: number, patch: Partial<Message>) => {
    setMessages((m) => m.map((msg) => (msg.id === id ? { ...msg, ...patch } : msg)));
  }, []);

  const sendMessage = useCallback(
    async (question: string) => {
      if (!question.trim() || loading) return;

      // Adiciona mensagem do usuário
      addMessage({ role: "user", content: question });
      setInput("");
      setLoading(true);

      // Cria placeholder da resposta em streaming
      const assistantId = addMessage({
        role: "assistant",
        content: "",
        streaming: true,
      });

      try {
        await api.chatStream(question, {
          onToken: (token) => {
            updateMessage(assistantId, {
              // Usa função de update para evitar closure stale
              content: "",   // será sobrescrito abaixo via setState funcional
            });
            setMessages((m) =>
              m.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, content: msg.content + token }
                  : msg
              )
            );
          },
          onSources: (sources) => {
            updateMessage(assistantId, { sources });
          },
          onDone: () => {
            updateMessage(assistantId, { streaming: false });
            setLoading(false);
          },
          onError: (errMsg) => {
            updateMessage(assistantId, {
              content: `Erro: ${errMsg}`,
              streaming: false,
              error: true,
            });
            setLoading(false);
          },
        });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Erro desconhecido";
        updateMessage(assistantId, {
          content: `Erro: ${msg}`,
          streaming: false,
          error: true,
        });
        setLoading(false);
      }
    },
    [loading, addMessage, updateMessage]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-12">
            <Bot className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500 font-medium">Assistente Financeiro IA</p>
            <p className="text-sm text-gray-400 mb-6">
              Perguntas em linguagem natural — dados 100% do banco, sem alucinação
            </p>
            <div className="grid grid-cols-2 gap-2 max-w-lg mx-auto">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className="text-sm text-left px-4 py-3 border border-gray-200 rounded-lg hover:bg-blue-50 hover:border-blue-300 transition-colors text-gray-600"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            {msg.role === "assistant" && (
              <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0 mt-1">
                <Bot className="w-4 h-4 text-white" />
              </div>
            )}

            <div className={`max-w-[75%] ${msg.role === "user" ? "order-first" : ""}`}>
              <div
                className={`rounded-xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white rounded-br-sm"
                    : msg.error
                    ? "bg-red-50 border border-red-200 text-red-700 rounded-bl-sm"
                    : "bg-white border border-gray-200 text-gray-800 rounded-bl-sm shadow-sm"
                }`}
              >
                {msg.content}
                {msg.streaming && !msg.content && <TypingDots />}
                {msg.streaming && msg.content && (
                  <span className="inline-block w-0.5 h-4 bg-gray-500 ml-0.5 animate-pulse align-middle" />
                )}
              </div>

              {msg.role === "assistant" && msg.sources && (
                <SourcesCard sources={msg.sources} />
              )}
            </div>

            {msg.role === "user" && (
              <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 mt-1">
                <User className="w-4 h-4 text-gray-600" />
              </div>
            )}
          </div>
        ))}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-100 p-4 bg-white">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Faça uma pergunta sobre as transações..."
            disabled={loading}
            className="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
            className="bg-blue-600 text-white rounded-xl px-4 py-2.5 hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
