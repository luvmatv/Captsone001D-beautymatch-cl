import { useEffect, useState } from "react";
import { api } from "../api.js";
import { SORTS } from "../format.js";
import { useApi } from "../useApi.js";
import { apiFilters, useDebounced, useFilters } from "../useFilters.js";
import Filters from "../components/Filters.jsx";
import Pagination from "../components/Pagination.jsx";
import ProductCard from "../components/ProductCard.jsx";
import { Empty, ErrorMessage, Loading } from "../components/Status.jsx";

const LIMIT = 24;

export default function Catalog() {
  const { lists, values, toggle, change, clear, setOffset, params } = useFilters();
  const [query, setQuery] = useState(values.q);
  const [retry, setRetry] = useState(0);
  const [showFilters, setShowFilters] = useState(false);
  useEffect(() => setQuery(values.q), [values.q]);

  const offset = Number(values.offset) || 0;
  // "Más relevantes" por defecto, con o sin búsqueda (la API, sin sort, ordenaría por nombre).
  const sort = values.sort || "relevance";
  const request = useDebounced(params.toString(), 350);

  const brands = useApi((opts) => api.brands(opts), []);
  const products = useApi(
    (opts) => api.products({ ...apiFilters(lists, values), q: values.q, sort, limit: LIMIT, offset }, opts),
    [request, retry]
  );
  const activeFilters = [...params.keys()].filter((k) => !["q", "sort", "offset"].includes(k)).length;

  return (
    <>
      <header className="page-head page-head-search">
        <div>
          <h1>Catálogo</h1>
          <p className="page-lead">El mismo frasco en seis tiendas chilenas, con el precio de cada mañana.</p>
        </div>
        <form className="search" role="search" onSubmit={(e) => { e.preventDefault(); change("q", query.trim()); }}>
          <label htmlFor="q" className="sr-only">Buscar perfume o marca</label>
          <input id="q" type="search" value={query} maxLength={100} autoComplete="off"
                 placeholder="Busca un perfume o una marca"
                 onChange={(e) => setQuery(e.target.value)} />
          <button type="submit" aria-label="Buscar">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></svg>
          </button>
        </form>
      </header>

      <div className="catalog">
        <aside className={`sidebar${showFilters ? " open" : ""}`} id="filtros">
          <Filters values={values} lists={lists} brands={brands.data?.items}
                   onToggle={toggle} onChange={change} onClear={clear} />
        </aside>

        <section className="results" aria-live="polite">
          <div className="results-bar">
            <p>
              {products.data ? <span className="results-count"><strong>{products.data.total.toLocaleString("es-CL")}</strong> productos</span> : " "}
              {values.q && <> para «{values.q}»</>}
            </p>
            <div className="results-tools">
              <button type="button" className="btn-quiet filters-toggle" aria-controls="filtros"
                      aria-expanded={showFilters} onClick={() => setShowFilters((s) => !s)}>
                Filtros{activeFilters ? ` (${activeFilters})` : ""}
              </button>
              <label>
                <span className="sr-only">Ordenar por</span>
                <select value={sort} onChange={(e) => change("sort", e.target.value === "relevance" ? "" : e.target.value)}>
                  {Object.entries(SORTS).map(([k, label]) => (
                    <option key={k} value={k}>{label}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {products.error && <ErrorMessage error={products.error} onRetry={() => setRetry((n) => n + 1)} />}
          {products.loading && !products.data && <Loading />}
          {products.data && products.data.items.length === 0 && (
            <Empty>
              <p>No hay perfumes a la venta que cumplan todo esto.</p>
              <button type="button" className="btn-quiet" onClick={clear}>Quitar filtros</button>
            </Empty>
          )}
          {products.data && (
            <div className={`grid${products.loading ? " is-loading" : ""}`}>
              {products.data.items.map((p) => <ProductCard key={p.product_id} product={p} />)}
            </div>
          )}
          {products.data && (
            <Pagination total={products.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          )}
        </section>
      </div>
    </>
  );
}
