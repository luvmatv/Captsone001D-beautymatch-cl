import { day, money, perMl, readOn, storeName, when } from "../format.js";

// Una barra por publicación, de largo proporcional al precio: se ve de un vistazo cuánto más cuesta en cada tienda.
// Los precios desactualizados (is_stale) van aparte y con su fecha: nunca son "el más barato" ni cuentan
// para las diferencias, porque no sabemos cuánto cuestan hoy.
export default function PriceLadder({ prices }) {
  const fresh = prices.filter((p) => !p.is_stale);
  const stale = prices.filter((p) => p.is_stale);
  const available = fresh.filter((p) => p.is_available);
  const max = Math.max(...prices.map((p) => p.list_price ?? p.price));
  const lowest = available.length ? Math.min(...available.map((p) => p.price)) : null;
  const lastStale = stale.length ? stale.map((p) => p.scraped_at).sort().at(-1) : null;

  const rung = (p) => {
    const isLowest = !p.is_stale && p.is_available && p.price === lowest;
    const diff = !p.is_stale && p.is_available && lowest !== null && p.price > lowest ? p.price - lowest : 0;
    const status = p.is_stale
      ? `Precio del ${day(p.scraped_at)}, no actualizado${p.is_available ? "" : ", sin stock"}`
      : !p.is_available ? "Sin stock" : isLowest ? "El más barato" : `${money(diff)} más caro`;
    const classes = ["rung", isLowest && "rung-lowest", !p.is_available && "rung-out", p.is_stale && "rung-stale"];
    return (
      <li key={p.listing_url} className={classes.filter(Boolean).join(" ")}>
        <div className="rung-head">
          <span className="rung-store">
            {storeName(p.store)}
            <time className="rung-date" dateTime={p.scraped_at} title={`Leído el ${when(p.scraped_at)}`}>
              {readOn(p.scraped_at)}
            </time>
          </span>
          <span className="rung-price">
            {p.list_price && <s className="muted">{money(p.list_price)}</s>} <strong>{money(p.price)}</strong>
          </span>
        </div>
        <div className="rung-track" aria-hidden="true">
          <div className="rung-bar" style={{ width: `${Math.max(8, (p.price / max) * 100)}%` }} />
        </div>
        <div className="rung-foot">
          <span>
            {status}
            {perMl(p.price_per_ml) && `, ${perMl(p.price_per_ml)}`}
          </span>
          <a href={p.listing_url} target="_blank" rel="noopener noreferrer">
            Ver en {storeName(p.store)}<span className="sr-only"> (abre otra pestaña)</span>
          </a>
        </div>
      </li>
    );
  };

  return (
    <>
      {lowest === null && (
        <div className="ladder-none">
          <strong>Sin precio vigente hoy</strong>
          <p>
            {stale.length
              ? `Las tiendas que lo publican no se han podido leer desde el ${day(lastStale)}: sus precios pueden haber cambiado.`
              : "Ninguna tienda lo tiene en stock hoy."}
          </p>
        </div>
      )}
      {fresh.length > 0 && <ol className="ladder">{fresh.map(rung)}</ol>}
      {stale.length > 0 && (
        <>
          <h3 className="ladder-divider">Sin lectura reciente</h3>
          <ol className="ladder">{stale.map(rung)}</ol>
        </>
      )}
    </>
  );
}
