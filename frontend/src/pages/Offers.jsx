import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { STORES, money, storeName } from "../format.js";
import { useApi } from "../useApi.js";
import Pagination from "../components/Pagination.jsx";
import ProductCard from "../components/ProductCard.jsx";
import { Empty, ErrorMessage, Loading } from "../components/Status.jsx";

const LIMIT = 24;

export default function Offers() {
  const [params, setParams] = useSearchParams();
  const [retry, setRetry] = useState(0);
  const stores = params.getAll("store");
  const offset = Number(params.get("offset")) || 0;
  const offers = useApi((opts) => api.offers({ store: stores, limit: LIMIT, offset }, opts), [params.toString(), retry]);

  const toggleStore = (key) => {
    const next = new URLSearchParams(params);
    next.delete("store");
    next.delete("offset");
    (stores.includes(key) ? stores.filter((s) => s !== key) : [...stores, key]).forEach((s) => next.append("store", s));
    setParams(next);
  };
  const setOffset = (value) => {
    const next = new URLSearchParams(params);
    value > 0 ? next.set("offset", value) : next.delete("offset");
    setParams(next);
    window.scrollTo({ top: 0 });
  };

  return (
    <div className="page">
      <header className="page-head">
        <h1>Ofertas reales</h1>
        <p className="hero-lead">
          Solo descuentos cuyo precio tachado es el que la tienda cobraba de verdad en los últimos 30 días.
          Ordenados por cuánto ahorras en pesos.
        </p>
      </header>
      <div className="chips" role="group" aria-label="Filtrar por tienda">
        {Object.entries(STORES).map(([key, label]) => (
          <button key={key} type="button" className="chip" aria-pressed={stores.includes(key)} onClick={() => toggleStore(key)}>
            {label}
          </button>
        ))}
      </div>

      {offers.error && <ErrorMessage error={offers.error} onRetry={() => setRetry((n) => n + 1)} />}
      {offers.loading && !offers.data && <Loading label="Buscando ofertas…" />}
      {offers.data?.items.length === 0 && (
        <Empty><p>No hay ofertas verificadas{stores.length ? " en estas tiendas" : ""} hoy. La lista crece a medida que se acumula historial.</p></Empty>
      )}
      {offers.data && (
        <div className={`grid${offers.loading ? " is-loading" : ""}`}>
          {offers.data.items.map((o) => (
            <ProductCard
              key={o.listing_url}
              product={{ ...o, lowest_price: o.price, lowest_price_store: o.store, best_discount_percent: o.discount_percent, price_per_ml: null }}
              extra={<p className="saving">Ahorras {money(o.discount_amount)} en {storeName(o.store)} (antes {money(o.list_price)})</p>}
            />
          ))}
        </div>
      )}
      {offers.data && <Pagination total={offers.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />}
    </div>
  );
}
