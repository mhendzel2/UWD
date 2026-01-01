import React, { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from "recharts";

type RegimeRow = {
  underlying: string;
  regime_label?: string;
  confidence_tier?: string;
};

type Props = {
  regimes: RegimeRow[];
};

const COLORS = ["#0088FE", "#00C49F", "#FFBB28", "#FF8042", "#8884d8"];

const ChartsPanel: React.FC<Props> = ({ regimes }) => {
  const regimeDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    regimes.forEach((r) => {
      const label = r.regime_label || "Unknown";
      counts[label] = (counts[label] || 0) + 1;
    });
    return Object.entries(counts).map(([name, value]) => ({ name, value }));
  }, [regimes]);

  const confidenceDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    regimes.forEach((r) => {
      const label = r.confidence_tier || "Unknown";
      counts[label] = (counts[label] || 0) + 1;
    });
    return Object.entries(counts).map(([name, value]) => ({ name, value }));
  }, [regimes]);

  if (regimes.length === 0) return null;

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "20px", marginTop: "20px" }}>
      <div style={{ flex: 1, minWidth: "300px", height: "300px", border: "1px solid #eee", padding: "10px" }}>
        <h4>Regime Distribution</h4>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={regimeDistribution}
              cx="50%"
              cy="50%"
              labelLine={false}
              label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
              outerRadius={80}
              fill="#8884d8"
              dataKey="value"
            >
              {regimeDistribution.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div style={{ flex: 1, minWidth: "300px", height: "300px", border: "1px solid #eee", padding: "10px" }}>
        <h4>Confidence Levels</h4>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={confidenceDistribution}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Legend />
            <Bar dataKey="value" fill="#82ca9d" name="Count" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default ChartsPanel;
