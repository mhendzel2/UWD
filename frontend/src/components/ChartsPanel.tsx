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
import "./ChartsPanel.css";

type RegimeRow = {
  underlying: string;
  regime_label?: string;
  confidence_tier?: string;
  dominant_horizon_hint?: string | null;
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

  const horizonDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    regimes.forEach((r) => {
      const label = r.dominant_horizon_hint || "Unknown";
      counts[label] = (counts[label] || 0) + 1;
    });
    return Object.entries(counts).map(([name, value]) => ({ name, value }));
  }, [regimes]);

  const regimeByConfidence = useMemo(() => {
    const tiers = ["HIGH", "MEDIUM", "LOW", "Unknown"] as const;
    const out: Record<string, any> = {};
    regimes.forEach((r) => {
      const regime = r.regime_label || "Unknown";
      const tier = (r.confidence_tier || "Unknown").toUpperCase();
      if (!out[regime]) {
        out[regime] = { regime };
        tiers.forEach((t) => (out[regime][t] = 0));
      }
      const key = (tiers as readonly string[]).includes(tier) ? tier : "Unknown";
      out[regime][key] += 1;
    });
    return Object.values(out);
  }, [regimes]);

  if (regimes.length === 0) return null;

  return (
    <div className="chartsWrap">
      <div className="chartCard">
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

      <div className="chartCard">
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

      <div className="chartCard">
        <h4>Dominant Horizon</h4>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={horizonDistribution}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Legend />
            <Bar dataKey="value" fill="#8884d8" name="Count" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="chartCardWide">
        <h4>Regime × Confidence</h4>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={regimeByConfidence}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="regime" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Legend />
            <Bar dataKey="HIGH" stackId="a" fill="#16a34a" name="High" />
            <Bar dataKey="MEDIUM" stackId="a" fill="#f59e0b" name="Medium" />
            <Bar dataKey="LOW" stackId="a" fill="#ef4444" name="Low" />
            <Bar dataKey="Unknown" stackId="a" fill="#94a3b8" name="Unknown" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default ChartsPanel;
