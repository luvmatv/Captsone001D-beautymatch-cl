import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { day, dayNumber, daysAgo, money, storeName } from "../format.js";

// Un color fijo por tienda (el color sigue a la tienda, nunca a su puesto). Validados con el script de dataviz
// sobre #F5F5F7: contraste ≥ 3:1 y separación para daltonismo. El mínimo del día va en tinta, distinto de todos.
export const STORE_COLORS = {
  salcobrand: "#2A78D6",
  preunic: "#D4572A",
  maicao: "#13906A",
  beautyperfumes: "#5D4FC9",
  dperfumes: "#9A7400",
  dreamsparfums: "#C2407A",
};
// La banda casi transparente con un borde fino arriba (el más caro); la línea del mínimo es lo que más se ve.
const INK = "#1D1D1F", INK_SOFT = "#6E6E73", BAND = "#1D1D1F", BAND_OPACITY = 0.035, TOP = "#AEAEB2", OTHER = "#6E6E73";
const colorOf = (store) => STORE_COLORS[store] ?? OTHER;

// Una tienda cuenta en un día si se leyó ese día o en los 2 anteriores (la misma regla del precio vigente).
// Si le faltan más días seguidos, su línea se corta en ese hueco: nunca se inventa un tramo.
const CARRY_DAYS = 2;
const DAY_MS = 86400000;
const xOf = (n) => n * DAY_MS + 12 * 3600000; // mediodía UTC: en Chile cae el mismo día

// Precio de una publicación en cada día de Chile: la última lectura del día; sin stock = sin precio.
function dailyValues(points) {
  const byDay = new Map();
  for (const p of points) byDay.set(dayNumber(new Date(p.scraped_at)), p.is_available ? p.price : null);
  return byDay;
}

// Eje Y con todo a la vista: va del precio más bajo al más alto de cualquier tienda en el período (también las
// que están ocultas en la leyenda, para que el eje no cambie al prenderlas), con un margen de 8 % del rango
// arriba y abajo, y marcas redondas. Recharts no recalcula ni recorta: recibe el dominio y las marcas listos.
export function yScale(rows) {
  const values = rows.flatMap((r) => Object.entries(r).filter(([k, v]) => /^s\d+$|^min$|^max$/.test(k) && v != null).map(([, v]) => v));
  if (!values.length) return { domain: [0, 1000], ticks: undefined };
  const lo = Math.min(...values), hi = Math.max(...values);
  const pad = Math.max((hi - lo) * 0.08, hi * 0.03, 500);
  const raw = (hi - lo + 2 * pad) / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((m) => m >= raw);
  const bottom = Math.max(0, Math.floor((lo - pad) / step) * step);
  const top = Math.ceil((hi + pad) / step) * step;
  const ticks = [];
  for (let v = bottom; v <= top + 1e-6; v += step) ticks.push(Math.round(v));
  return { domain: [bottom, top], ticks };
}

export function buildDays(series) {
  const lines = series.map((s) => ({ ...s, days: dailyValues(s.points) }));
  const all = lines.flatMap((l) => [...l.days.keys()]);
  if (!all.length) return { rows: [], lines };
  const first = Math.min(...all), last = Math.max(...all);
  const rows = [];
  for (let n = first; n <= last; n++) rows.push({ n, t: xOf(n) });
  lines.forEach((line, i) => {
    const key = `s${i}`;
    const lastRead = Math.max(...line.days.keys());
    let carried = null, carriedFrom = null;
    for (const row of rows) {
      if (row.n > lastRead) break;                        // después de su última lectura no se extiende
      if (line.days.has(row.n)) { carried = line.days.get(row.n); carriedFrom = row.n; }
      if (carriedFrom === null || row.n - carriedFrom > CARRY_DAYS) continue;
      row[key] = carried;
    }
  });
  for (const row of rows) {
    const values = lines.map((_, i) => row[`s${i}`]).filter((v) => v != null);
    if (values.length) {
      row.min = Math.min(...values);
      row.max = Math.max(...values);
      row.band = [row.min, row.max];
    }
  }
  return { rows, lines };
}

function Swatch({ color, band }) {
  return (
    <svg className="swatch" width="22" height="10" aria-hidden="true">
      {band ? <>
        <rect x="1" y="1" width="20" height="8" fill={BAND} fillOpacity={BAND_OPACITY * 2} />
        <line x1="1" y1="1" x2="21" y2="1" stroke={TOP} strokeWidth="1" />
      </> : null}
      <line x1="1" y1="8" x2="21" y2="8" stroke={color} strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

function ChartTooltip({ active, payload, label, lines }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  const rows = lines.map((l) => ({ l, value: row[l.key] })).filter((r) => r.value != null)
    .sort((a, b) => a.value - b.value);
  return (
    <div className="chart-tip">
      <p className="chart-tip-when">{day(label)}</p>
      {rows.length === 0 ? <p className="chart-tip-none">Sin precios leídos ese día</p> : (
        <ul>
          {rows.map(({ l, value }) => (
            <li key={l.key}>
              <span className="chart-tip-dot" style={{ background: l.color }} aria-hidden="true" />
              <span>{l.name}</span>
              <strong className="num">{money(value)}</strong>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// El punto al final de la última lectura de una tienda desactualizada (no se puntea su línea).
function EndDot({ cx, cy, index, lastIndex, color }) {
  if (index !== lastIndex || cx == null || cy == null) return null;
  return <circle cx={cx} cy={cy} r={4.5} fill="#F5F5F7" stroke={color} strokeWidth={2.5} />;
}

// Historial del producto. Por defecto: el precio más bajo de cada día y, detrás, la banda entre el más barato
// y el más caro de ese día. Cada tienda se agrega tocando su chip; el tooltip muestra todas las tiendas del día.
export default function PriceChart({ series, prices = [], cheapestUrl }) {
  const [chosen, setChosen] = useState(() => new Set());
  const { rows, lines: raw } = buildDays(series);
  if (rows.length < 2) return <p className="muted">Todavía hay muy pocas lecturas para dibujar un historial. Se agrega una cada mañana.</p>;

  const current = new Map(prices.map((p) => [p.listing_url, p]));
  const lines = raw.map((s, i) => {
    const repeated = raw.filter((o) => o.store === s.store).length > 1;
    const now = current.get(s.listing_url);
    const key = `s${i}`;
    return {
      key, store: s.store, color: colorOf(s.store), last: s.points[s.points.length - 1],
      name: storeName(s.store) + (repeated ? ` (${i + 1})` : ""),
      cheapest: s.listing_url === cheapestUrl,
      stale: !now || now.is_stale,
      lastIndex: rows.reduce((at, row, n) => (row[key] !== undefined ? n : at), -1),
    };
  });
  const single = lines.length === 1;
  const y = yScale(rows);
  // Chips: la más barata primero, luego por precio de la última lectura; las desactualizadas al final.
  const chips = [...lines].sort((a, b) =>
    (b.cheapest - a.cheapest) || (a.stale - b.stale) || (a.last.price - b.last.price));
  const toggle = (key) => setChosen((s) => {
    const next = new Set(s);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const first = rows.find((r) => r.min != null), lastRow = [...rows].reverse().find((r) => r.min != null);
  const change = first && lastRow ? lastRow.min - first.min : 0;

  return (
    <div className="chart">
      <p className="chart-key">
        <Swatch color={INK} band={!single} />
        <span>{single ? `Precio en ${lines[0].name}` : "Precio más bajo del día"}</span>
        {!single && <span className="key-note">La banda gris llega hasta el más caro de cada día.</span>}
      </p>
      {!single && (
        <ul className="chart-legend" aria-label="Agregar una tienda al gráfico">
          {chips.map((l) => {
            const on = chosen.has(l.key);
            return (
              <li key={l.key}>
                <button type="button" className={`legend-item${on ? " on" : ""}`} aria-pressed={on} onClick={() => toggle(l.key)}>
                  <span className="chip-dot" style={{ borderColor: l.color, background: on ? l.color : "transparent" }} aria-hidden="true" />
                  <span className="legend-name">{l.name}</span>
                  <span className="legend-meta">
                    <span className="legend-price num">{l.last.is_available ? money(l.last.price) : "Sin stock"}</span>
                    {l.cheapest && <span className="legend-tag">Más barata</span>}
                    {l.stale && <span className="legend-old">hace {daysAgo(l.last.scraped_at)} días</span>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div role="img" aria-label={first && lastRow
        ? `Precio más bajo del día entre ${lines.length} ${lines.length === 1 ? "tienda" : "tiendas"}: ${money(first.min)} el ${day(first.t)} y ${money(lastRow.min)} el ${day(lastRow.t)}${change ? ` (${change < 0 ? "bajó" : "subió"} ${money(Math.abs(change))})` : ""}.`
        : "Historial de precios"}>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={rows} margin={{ top: 16, right: 12, bottom: 0, left: 4 }}>
            <CartesianGrid stroke="#DCDCE0" vertical={false} />
            <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={(t) => day(t)}
                   stroke={INK_SOFT} tickLine={false} axisLine={false} fontSize={12} minTickGap={40} />
            <YAxis tickFormatter={(v) => money(v)} width={84} stroke={INK_SOFT} tickLine={false} axisLine={false} fontSize={12}
                   domain={y.domain} ticks={y.ticks} interval={0} allowDataOverflow={false} />
            <Tooltip content={<ChartTooltip lines={lines} />} cursor={{ stroke: "#C7C7CC", strokeWidth: 1 }} />
            {!single && (
              // Curva suave (no escalones): los cambios del más caro no se leen como huecos
              <Area dataKey="band" type="monotoneX" stroke="none" fill={BAND} fillOpacity={BAND_OPACITY}
                    isAnimationActive={false} activeDot={false} connectNulls={false} />
            )}
            {!single && (
              <Line dataKey="max" name="Más caro del día" type="monotoneX" stroke={TOP} strokeWidth={1}
                    dot={false} activeDot={false} connectNulls={false} isAnimationActive={false} />
            )}
            {/* el mínimo debajo: si una tienda es la más barata ese día, su color queda encima con borde de tinta */}
            <Line dataKey="min" name="Más bajo del día" stroke={INK} strokeWidth={2.75} type="stepAfter"
                  connectNulls={false} isAnimationActive={false} dot={false}
                  activeDot={{ r: 4.5, strokeWidth: 2, stroke: "#F5F5F7", fill: INK }} />
            {lines.filter((l) => chosen.has(l.key)).map((l) => (
              <Line key={l.key} dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={2}
                    type="stepAfter" connectNulls={false} isAnimationActive={false}
                    dot={l.stale ? <EndDot lastIndex={l.lastIndex} color={l.color} /> : false}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: "#F5F5F7" }} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {single && <p className="chart-foot">Solo {lines[0].name} vende este producto: la línea es su precio de cada día.</p>}
    </div>
  );
}
