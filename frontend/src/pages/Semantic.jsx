import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { useApi } from "../useApi.js";
import ProductCard from "../components/ProductCard.jsx";
import { Empty, ErrorMessage, Loading } from "../components/Status.jsx";

const EXAMPLES = ["perfume árabe de vainilla", "colonia fresca para hombre", "body mist frutal", "set de regalo para mujer"];

export default function Semantic() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [text, setText] = useState(q);
  const [retry, setRetry] = useState(0);
  useEffect(() => setText(q), [q]);

  const result = useApi((opts) => (q ? api.semantic({ q, limit: 24 }, opts) : Promise.resolve(null)), [q, retry]);

  // Mientras el modelo carga (unos 20-30 s después de que la API despierta) responde 503 con Retry-After.
  useEffect(() => {
    if (result.error?.status === 503 && result.error.retryAfter) {
      const id = setTimeout(() => setRetry((n) => n + 1), result.error.retryAfter * 1000);
      return () => clearTimeout(id);
    }
  }, [result.error]);

  const search = (value) => setParams(value.trim() ? { q: value.trim() } : {});
  return (
    <div className="page">
      <header className="page-head">
        <h1>Buscar por descripción</h1>
        <p className="hero-lead">
          Escribe lo que buscas con tus palabras. Entiende sinónimos y errores de ortografía, pero solo conoce el nombre
          de cada perfume, no sus notas olfativas.
        </p>
      </header>
      <form className="search search-wide" role="search" onSubmit={(e) => { e.preventDefault(); search(text); }}>
        <label htmlFor="semantic" className="sr-only">Describe el perfume que buscas</label>
        <input id="semantic" type="search" maxLength={200} value={text} onChange={(e) => setText(e.target.value)}
               placeholder="Ej.: perfume árabe de vainilla" />
        <button type="submit">Buscar</button>
      </form>
      {!q && (
        <div className="chips" aria-label="Ejemplos">
          {EXAMPLES.map((e) => <button key={e} type="button" className="chip" onClick={() => search(e)}>{e}</button>)}
        </div>
      )}
      {q && result.loading && <Loading label="Buscando perfumes parecidos…" />}
      {result.error?.status === 503 && result.error.retryAfter
        ? <Loading label="El buscador se está preparando. Reintentamos solos en unos segundos…" />
        : result.error && <ErrorMessage error={result.error} onRetry={() => setRetry((n) => n + 1)} />}
      {result.data?.items.length === 0 && <Empty><p>No encontramos perfumes a la venta parecidos a «{q}». Prueba con otras palabras.</p></Empty>}
      {result.data?.items.length > 0 && (
        <div className="grid">
          {result.data.items.map((p) => <ProductCard key={p.product_id} product={p} />)}
        </div>
      )}
    </div>
  );
}
