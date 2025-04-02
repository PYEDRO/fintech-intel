"use client";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from "recharts";
import type { MonthlyEvolution, Projection } from "@/lib/api";

interface Props {
  data: MonthlyEvolution[];
  projection?: Projection[];
}

function fmtBRL(v: number) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", notation: "compact" }).format(v);
}

export default function RevenueChart({ data, projection = [] }: Props) {
  const chartData = [
    ...data.map((d) => ({ mes: d.mes.slice(0, 7), receita: d.receita, count: d.count })),
    ...projection.map((p) => ({ mes: p.mes, receita_proj: p.receita_projetada })),
  ];

  if (!chartData.length) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 h-64 flex items-center justify-center text-gray-400 text-sm">
        Sem dados disponíveis
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h3 className="font-semibold text-gray-800 mb-4">Evolução Mensal de Receita</h3>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="mes" tick={{ fontSize: 11 }} />
          <YAxis tickFormatter={fmtBRL} tick={{ fontSize: 11 }} width={70} />
          <Tooltip formatter={(v: number) => fmtBRL(v)} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone"
            dataKey="receita"
            name="Receita Realizada"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
          />
          {projection.length > 0 && (
            <Line
              type="monotone"
              dataKey="receita_proj"
              name="Projeção"
              stroke="#f59e0b"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={{ r: 3 }}
            />
          )}
          {projection.length > 0 && (
            <ReferenceLine
              x={data[data.length - 1]?.mes.slice(0, 7)}
              stroke="#e5e7eb"
              strokeDasharray="4 4"
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
