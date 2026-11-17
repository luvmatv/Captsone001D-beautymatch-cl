import { day, money, perMl, readOn, storeName, when } from "../format.js";

// Comparación de precios de un producto. Solo los precios vigentes y con stock compiten por "el más barato";
// los desactualizados (is_stale) van aparte, con su fecha, y nunca cuentan para el más barato ni para las diferencias.
export function splitPrices(prices) {
  const fresh = prices.filter((p) => !p.is_stale);
  const stale = prices.filter((p) => p.is_stale);
  const available = fresh.filter((p) => p.is_available);
  const lowest = available.length ? Math.min(...available.map((p) => p.price)) : null;
  const cheapest = available.find((p) => p.price === lowest) ?? null;
  return { fresh, stale, lowest, cheapest, isLowest: (p) => !p.is_stale && p.is_available && p.price === lowest };
}

export default function PriceLadder({ prices }) {
  const { fresh, stale, lowest, isLowest } = splitPrices(prices);
  const scale = Math.max(...prices.map((p) => p.list_price ?? p.price));

  const row = (p, i) => {
    const status = p.is_stale ? "No cuenta para el más barato"
      : !p.is_available ? "Sin stock" : isLowest(p) ? "El más barato hoy" : `${money(p.price - lowest)} más caro`;
    const classes = ["row", isLowest(p) && "lowest", !p.is_available && "out", p.is_stale && "stale"].filter(Boolean).join(" ");
    return (
      <li key={p.listing_url} className={classes} style={{ "--i": i }}>
        <a className="row-link" href={p.listing_url} target="_blank" rel="noopener noreferrer">
          <span className="row-store">
            {storeName(p.store)}
            <time className="row-date" dateTime={p.scraped_at} title={`Leído el ${when(p.scraped_at)}`}>
              {p.is_stale ? `Precio del ${day(p.scraped_at)}, no actualizado` : readOn(p.scraped_at)}
            </time>
          </span>
          <span className="row-price num">
            {p.list_price && <s>{money(p.list_price)}</s>}{money(p.price)}
          </span>
          <span className="row-track" aria-hidden="true">
            <span className="row-fill" style={{ "--w": `${Math.max(6, (p.price / scale) * 100)}%` }} />
          </span>
          <span className="row-foot">
            <span className="row-diff">{status}{perMl(p.price_per_ml) && ` · ${perMl(p.price_per_ml)}`}</span>
            <span className="row-go">Ver en {storeName(p.store)} ›<span className="sr-only"> (abre otra pestaña)</span></span>
          </span>
        </a>
      </li>
    );
  };

  return (
    <>
      {fresh.length > 0 && <ol className="rows">{fresh.map(row)}</ol>}
      {stale.length > 0 && (
        <>
          <h3 className="rows-label">Sin lectura reciente</h3>
          <ol className="rows">{stale.map((p, i) => row(p, i + fresh.length))}</ol>
        </>
      )}
    </>
  );
}
