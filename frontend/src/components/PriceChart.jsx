import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { day, daysAgo, money, storeName, when } from "../format.js";

// Un color fijo por tienda (el color sigue a la tienda, nunca a su puesto en el ranking).
// Validados con el script de dataviz sobre #F5F5F7: contraste ≥ 3:1 y separación para daltonismo
// en este orden (azul, naranjo, verde, violeta, ocre, magenta). El azul de acento queda para la UI.
export const STORE_COLORS = {
  salcobrand: "#2A78D6",
  preunic: "#D4572A",
  maicao: "#13906A",
  beautyperfumes: "#5D4FC9",
  dperfumes: "#9A7400",
  dreamsparfums: "#C2407A",
};
const OTHER = "#6E6E73", INK_SOFT = "#6E6E73";
const colorOf = (store) => STORE_COLORS[store] ?? OTHER;

// Muestra de la línea en la leyenda y el tooltip: sólida o punteada, igual que en el gráfico.
function Swatch({ color, dashed, thick }) {
  return (
    <svg className="swatch" width="22" height="8" aria-hidden="true">
      <line x1="1" y1="4" x2="21" y2="4" stroke={color} strokeWidth={thick ? 3 : 2}
            strokeDasharray={dashed ? "4 3" : undefined} strokeLinecap="round" />
    </svg>
  );
}

function ChartTooltip({ active, payload, label, lines }) {
  if (!active || !payload?.length) return null;
  const byKey = new Map(lines.map((l) => [l.key, l]));
  const rows = payload.filter((p) => p.value != null).sort((a, b) => a.value - b.value);
  return (
    <div className="chart-tip">
      <p className="chart-tip-when">{when(label)}</p>
      <ul>
        {rows.map((p) => {
          const l = byKey.get(p.dataKey);
          return (
            <li key={p.dataKey}>
              <Swatch color={l.color} dashed={l.stale} />
              <span>{l.name}</span>
              <strong className="num">{money(p.value)}</strong>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// Historial: una línea por publicación (la clave es listing_url, no la tienda).
// - La publicación más barata hoy va más gruesa y encima de las demás.
// - Las publicaciones sin precio vigente (is_stale, o ya no activas) van punteadas.
// - Pasar el mouse, enfocar o tocar una tienda de la leyenda (o su línea) la destaca y atenúa las demás.
export default function PriceChart({ series, prices = [], cheapestUrl }) {
  const [hovered, setHovered] = useState(null);
  const [pinned, setPinned] = useState(null);
  const active = hovered ?? pinned;

  const current = new Map(prices.map((p) => [p.listing_url, p]));
  const lines = series.map((s, i) => {
    const repeated = series.filter((o) => o.store === s.store).length > 1;
    const now = current.get(s.listing_url);
    const last = s.points[s.points.length - 1];
    return {
      key: `s${i}`,
      store: s.store,
      name: storeName(s.store) + (repeated ? ` (${i + 1})` : ""),
      points: s.points,
      color: colorOf(s.store),
      cheapest: s.listing_url === cheapestUrl,
      stale: !now || now.is_stale,
      last,
    };
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
  // Cada tienda se lee a otra hora: entre su primera y su última lectura, cada fila arrastra el último
  // valor leído (igual que la línea escalonada), para que el tooltip muestre todas las tiendas a la vez.
  for (const line of lines) {
    const first = new Date(line.points[0].scraped_at).getTime();
    const end = new Date(line.last.scraped_at).getTime();
    let carry = null;
    for (const row of data) {
      if (row.t < first || row.t > end) continue;
      if (line.key in row) carry = row[line.key];
      else row[line.key] = carry;
    }
  }
  const totalPoints = lines.reduce((n, l) => n + l.points.length, 0);
  if (totalPoints < 2) return <p className="muted">Todavía hay muy pocas lecturas para dibujar un historial. Se agrega una cada mañana.</p>;

  // Leyenda: la más barata primero, luego por precio de la última lectura; las desactualizadas al final.
  const legend = [...lines].sort((a, b) =>
    (b.cheapest - a.cheapest) || (a.stale - b.stale) || (a.last.price - b.last.price));
  // Orden de dibujo: la destacada (activa o, si no hay, la más barata) al final, encima de todo.
  const top = (l) => (active ? l.key === active : l.cheapest);
  const ordered = [...lines].sort((a, b) => top(a) - top(b));
  const cheapestLine = lines.find((l) => l.cheapest);

  return (
    <div className="chart">
      <ul className="chart-legend" aria-label="Tiendas del gráfico">
        {legend.map((l) => {
          const dim = active && active !== l.key;
          return (
            <li key={l.key}>
              <button type="button" className={`legend-item${dim ? " dim" : ""}${active === l.key ? " on" : ""}`}
                      aria-pressed={pinned === l.key}
                      onMouseEnter={() => setHovered(l.key)} onMouseLeave={() => setHovered(null)}
                      onFocus={() => setHovered(l.key)} onBlur={() => setHovered(null)}
                      onClick={() => setPinned((k) => (k === l.key ? null : l.key))}>
                <Swatch color={l.color} dashed={l.stale} thick={l.cheapest} />
                <span className="legend-name">{l.name}</span>
                <span className="legend-meta">
                  <span className="legend-price num">{l.last.is_available ? money(l.last.price) : "Sin stock"}</span>
                  {l.cheapest && <span className="legend-tag">Más barata</span>}
                  {!l.cheapest && l.stale && <span className="legend-old">hace {daysAgo(l.last.scraped_at)} días</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div role="img"
           aria-label={`Historial de precios en ${lines.map((l) => l.name).join(", ")}${cheapestLine ? `; la más barata hoy es ${cheapestLine.name}` : ""}`}>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data} margin={{ top: 10, right: 12, bottom: 0, left: 4 }}
                     onMouseLeave={() => setHovered(null)}>
            <CartesianGrid stroke="#DCDCE0" vertical={false} />
            <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={(t) => day(t)}
                   stroke={INK_SOFT} tickLine={false} axisLine={false} fontSize={12} minTickGap={40} />
            <YAxis tickFormatter={(v) => money(v)} width={84} stroke={INK_SOFT} tickLine={false} axisLine={false} fontSize={12}
                   domain={[(min) => Math.floor((min * 0.95) / 1000) * 1000, (max) => Math.ceil((max * 1.05) / 1000) * 1000]} />
            <Tooltip content={<ChartTooltip lines={lines} />} cursor={{ stroke: "#C7C7CC", strokeWidth: 1 }} />
            {ordered.map((l) => {
              const dim = active && active !== l.key;
              const strong = active ? active === l.key : l.cheapest;
              return (
                <Line key={l.key} dataKey={l.key} name={l.name} stroke={l.color}
                      strokeWidth={strong ? 3 : 1.75} strokeOpacity={dim ? 0.15 : 1}
                      strokeDasharray={l.stale ? "5 4" : undefined}
                      dot={false} activeDot={dim ? false : { r: 4, strokeWidth: 2, stroke: "#F5F5F7" }}
                      connectNulls type="stepAfter" isAnimationActive={false}
                      onMouseEnter={() => setHovered(l.key)}
                      onClick={() => setPinned((k) => (k === l.key ? null : l.key))} />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
