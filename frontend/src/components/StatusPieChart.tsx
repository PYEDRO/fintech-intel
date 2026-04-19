"use client";
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip, Legend } from "recharts";

const COLORS: Record<string, string> = {
  pago: "#22c55e",
  pendente: "#f59e0b",
  atrasado: "#ef4444",
};

interface Props {
  data: Record<string, number>;
}

export default function StatusPieChart({ data }: Props) {
  const chartData = Object.entries(data).map(([name, value]) => ({ name, value }));

  if (!chartData.length) return null;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h3 className="font-semibold text-gray-800 mb-4">Distribuição por Status</h3>
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            innerRadius={60}
            outerRadius={90}
            paddingAngle={3}
            dataKey="value"
            label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
            labelLine={false}
          >
            {chartData.map((entry) => (
              <Cell key={entry.name} fill={COLORS[entry.name] ?? "#6b7280"} />
            ))}
          </Pie>
          <Tooltip formatter={(v: number) => v.toLocaleString("pt-BR")} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
