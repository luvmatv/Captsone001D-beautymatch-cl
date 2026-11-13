import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { STORE_COLORS, day, money, storeName, when } from "../format.js";

// Historial: una línea por publicación (la clave es listing_url, no la tienda).
export default function PriceChart({ series }) {
  const lines = series.map((s, i) => {
    const repeated = series.filter((o) => o.store === s.store).length > 1;
    return { key: `s${i}`, name: storeName(s.store) + (repeated ? ` (${i + 1})` : ""), color: STORE_COLORS[s.store] ?? "#6B6578", points: s.points };
  });
  const byTime = new Map();
  for (const line of lines) {
    for (const p of line.points) {
      const t = new Date(p.scraped_at).getTime();
      const row = byTime.get(t) ?? { t };
      row[line.key] = p.is_available ? p.price : null;
      byTime.set(t, row);
    }
  }
  const data = [...byTime.values()].sort((a, b) => a.t - b.t);
  const totalPoints = lines.reduce((n, l) => n + l.points.length, 0);
  if (totalPoints < 2) return <p className="muted">Todavía hay muy pocas lecturas para dibujar un historial. Se agrega una cada mañana.</p>;
  return (
    <div className="chart" role="img" aria-label={`Historial de precios en ${lines.map((l) => l.name).join(", ")}`}>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
          <CartesianGrid stroke="#DCD8E8" vertical={false} />
          <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]}
                 tickFormatter={(t) => day(t)} stroke="#6B6578" fontSize={12} />
          <YAxis tickFormatter={(v) => money(v)} width={84} stroke="#6B6578" fontSize={12} domain={["auto", "auto"]} />
          <Tooltip labelFormatter={(t) => when(t)} formatter={(v) => money(v)} />
          <Legend />
          {lines.map((l) => (
            <Line key={l.key} dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={2}
                  dot={{ r: 3 }} connectNulls type="stepAfter" isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
