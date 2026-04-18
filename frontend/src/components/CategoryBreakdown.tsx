"use client";
import type { CategoryMetric } from "@/lib/api";

interface Props {
  data: CategoryMetric[];
}

function fmtBRL(v: number) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v);
}

export default function CategoryBreakdown({ data }: Props) {
  if (!data.length) return null;

  const maxReceita = Math.max(...data.map((d) => d.receita));

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h3 className="font-semibold text-gray-800 mb-4">Categorias (classificação IA)</h3>
      <div className="space-y-3">
        {data.slice(0, 7).map((item) => (
          <div key={item.categoria}>
            <div className="flex justify-between text-sm mb-1">
              <span className="text-gray-700 font-medium truncate pr-2">{item.categoria}</span>
              <span className="text-gray-500 text-xs whitespace-nowrap">{fmtBRL(item.receita)} · {item.count} txn</span>
            </div>
            <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all"
                style={{ width: `${(item.receita / maxReceita) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
