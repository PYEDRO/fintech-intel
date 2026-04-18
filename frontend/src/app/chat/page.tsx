import ChatInterface from "@/components/ChatInterface";

export default function ChatPage() {
  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-100 bg-white">
        <h1 className="text-xl font-bold text-gray-900">Chat Financeiro IA</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Consulte transações em linguagem natural com busca semântica (RAG)
        </p>
      </div>
      <div className="flex-1 overflow-hidden">
        <ChatInterface />
      </div>
    </div>
  );
}
