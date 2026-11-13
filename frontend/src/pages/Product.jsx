import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { CONCENTRATIONS, PRESENTATIONS, money, storeName, when } from "../format.js";
import { useApi } from "../useApi.js";
import PriceChart from "../components/PriceChart.jsx";
import PriceLadder from "../components/PriceLadder.jsx";
import ProductCard, { Bottle } from "../components/ProductCard.jsx";
import { ErrorMessage, Loading } from "../components/Status.jsx";

function ListPriceNotes({ checks }) {
  const notes = checks.filter((c) => c.list_price && c.vs_history.status !== "no_list_price");
  if (!notes.length) return null;
  const text = {
    consistent: "El precio tachado coincide con lo que esta tienda cobraba antes. Descuento real.",
    above_history: "El precio tachado es más alto que lo que esta tienda cobraba antes sin descuento.",
    insufficient_data: "Aún no hay suficiente historial para saber si el precio tachado es real.",
  };
  return (
    <section className="panel">
      <h2>¿Los descuentos son reales?</h2>
      <ul className="checks">
        {notes.map((c) => (
          <li key={c.listing_url} className={`check-${c.vs_history.status}`}>
            <strong>{storeName(c.store)}</strong>: {money(c.price)} en vez de {money(c.list_price)}.{" "}
            {text[c.vs_history.status]}
            {c.vs_history.status === "above_history" && c.vs_history.reference_price &&
              ` Su precio normal era ${money(c.vs_history.reference_price)}.`}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Product() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [retry, setRetry] = useState(0);
  const product = useApi((opts) => api.product(id, opts), [id, retry]);
  const history = useApi((opts) => api.priceHistory(id, opts), [id]);
  const checks = useApi((opts) => api.listPriceChecks(id, opts), [id]);
  const variants = useApi((opts) => api.variants(id, opts), [id]);

  // Producto fusionado con otro: la API redirige (308); dejamos la URL con el id vigente.
  useEffect(() => {
    if (product.data?.__movedTo && product.data.__movedTo !== id) navigate(`/producto/${product.data.__movedTo}`, { replace: true });
  }, [product.data, id, navigate]);
  useEffect(() => {
    if (product.data) document.title = `${product.data.canonical_name} | BeautyMatch CL`;
    return () => { document.title = "BeautyMatch CL"; };
  }, [product.data]);

  if (product.loading && !product.data) return <div className="page"><Loading label="Cargando producto…" /></div>;
  if (product.error) {
    const missing = product.error.status === 404 || product.error.status === 410 || product.error.status === 422;
    return (
      <div className="page">
        {missing ? (
          <div className="status">
            <h1>Este producto ya no está en el catálogo</h1>
            <p>Puede que la tienda lo haya retirado. Búscalo por su nombre para ver alternativas.</p>
            <Link to="/" className="btn">Ir al catálogo</Link>
          </div>
        ) : <ErrorMessage error={product.error} onRetry={() => setRetry((n) => n + 1)} />}
      </div>
    );
  }

  const p = product.data;
  const facts = [
    [ "Concentración", CONCENTRATIONS[p.concentration] ?? "No informada" ],
    [ "Tamaño", `${p.volume_ml} ml` ],
    [ "Presentación", PRESENTATIONS[p.presentation] ?? "—" ],
  ];
  return (
    <div className="page product">
      <nav className="crumbs" aria-label="Ruta">
        <Link to="/">Catálogo</Link> / <Link to={`/?brand=${encodeURIComponent(p.brand)}`}>{p.brand}</Link>
      </nav>

      <div className="product-top">
        <div className="product-image">{p.image_url ? <img src={p.image_url} alt={p.canonical_name} /> : <Bottle />}</div>
        <div className="product-main">
          <p className="card-brand">{p.brand}</p>
          <h1>{p.canonical_name}</h1>
          <dl className="facts">
            {facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
          </dl>
          {p.prices.length ? (
            <>
              <h2 className="ladder-title">Precio en cada tienda</h2>
              <PriceLadder prices={p.prices} />
              {p.last_updated && <p className="muted small">Precios leídos por última vez el {when(p.last_updated)}</p>}
            </>
          ) : <p className="status">Hoy ninguna tienda publica este producto.</p>}
        </div>
      </div>

      {checks.data && <ListPriceNotes checks={checks.data.checks} />}

      <section className="panel">
        <h2>Cómo ha cambiado el precio</h2>
        {history.loading && <Loading label="Cargando historial…" />}
        {history.error && <ErrorMessage error={history.error} />}
        {history.data && <PriceChart series={history.data.series} />}
      </section>

      {variants.data?.items?.length > 0 && (
        <section className="panel-plain">
          <h2>Otros tamaños y presentaciones</h2>
          <div className="grid grid-small">
            {variants.data.items.map((v) => <ProductCard key={v.product_id} product={v} />)}
          </div>
        </section>
      )}
    </div>
  );
}
