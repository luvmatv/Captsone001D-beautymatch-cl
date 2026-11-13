import { money, perMl, storeName, when } from "../format.js";

// Una barra por publicación, de largo proporcional al precio: se ve de un vistazo cuánto más cuesta en cada tienda.
export default function PriceLadder({ prices }) {
  const available = prices.filter((p) => p.is_available);
  const max = Math.max(...prices.map((p) => p.list_price ?? p.price));
  const lowest = available.length ? Math.min(...available.map((p) => p.price)) : null;
  return (
    <ol className="ladder">
      {prices.map((p) => {
        const isLowest = p.is_available && p.price === lowest;
        const diff = p.is_available && lowest !== null && p.price > lowest ? p.price - lowest : 0;
        return (
          <li key={p.listing_url} className={`rung${isLowest ? " rung-lowest" : ""}${p.is_available ? "" : " rung-out"}`}>
            <div className="rung-head">
              <span className="rung-store">{storeName(p.store)}</span>
              <span className="rung-price">
                {p.list_price && <s className="muted">{money(p.list_price)}</s>} <strong>{money(p.price)}</strong>
              </span>
            </div>
            <div className="rung-track" aria-hidden="true">
              <div className="rung-bar" style={{ width: `${Math.max(8, (p.price / max) * 100)}%` }} />
            </div>
            <div className="rung-foot">
              <span>
                {!p.is_available ? "Sin stock" : isLowest ? "El más barato" : `${money(diff)} más caro`}
                {perMl(p.price_per_ml) && `, ${perMl(p.price_per_ml)}`}
              </span>
              <a href={p.listing_url} target="_blank" rel="noopener noreferrer">
                Ver en {storeName(p.store)}<span className="sr-only"> (abre otra pestaña)</span>
              </a>
            </div>
            <span className="sr-only">Precio leído el {when(p.scraped_at)}</span>
          </li>
        );
      })}
    </ol>
  );
}
