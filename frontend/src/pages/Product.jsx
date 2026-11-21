import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { CONCENTRATIONS, PRESENTATIONS, bestImage, money, nameWithoutBrand, perMl, readOn, storeName } from "../format.js";
import { useApi } from "../useApi.js";
import PriceChart from "../components/PriceChart.jsx";
import PriceLadder, { splitPrices } from "../components/PriceLadder.jsx";
import ProductCard, { ProductImage } from "../components/ProductCard.jsx";
import { ErrorMessage, Loading } from "../components/Status.jsx";

const DAY_MS = 86400000;

// Ficha compacta con datos reales del catálogo: la base no guarda descripciones ni notas olfativas de las
// tiendas (raw_description está vacía), así que no se muestra ninguna; tampoco se generan con IA.
// El rango de 30 días sale del historial de lecturas con stock de todas las tiendas.
function About({ product, history, cheapest }) {
  const since = Date.now() - 30 * DAY_MS;
  const recent = (history?.series ?? []).flatMap((s) => s.points)
    .filter((pt) => pt.is_available && Date.parse(pt.scraped_at) >= since).map((pt) => pt.price);
  const fresh = product.prices.filter((x) => !x.is_stale);
  const stores = new Set(fresh.filter((x) => x.is_available).map((x) => x.store)).size;
  const facts = [
    ["Marca", product.brand],
    ["Concentración", CONCENTRATIONS[product.concentration]],
    ["Tamaño", product.volume_ml ? `${product.volume_ml} ml` : null],
    ["Presentación", PRESENTATIONS[product.presentation]],
    ["Precio por ml", cheapest ? `${perMl(cheapest.price_per_ml)} en ${storeName(cheapest.store)}` : null],
    ["Últimos 30 días", recent.length ? `entre ${money(Math.min(...recent))} y ${money(Math.max(...recent))}` : null],
    ["Tiendas con stock hoy", `${stores} de ${new Set(product.prices.map((x) => x.store)).size}`],
  ].filter(([, v]) => v && !String(v).includes("null"));
  const question = `Cuéntame sobre ${product.canonical_name}: ¿a qué huele y para quién es? ¿Conviene comprarlo hoy?`;
  return (
    <section className="panel about" aria-labelledby="about-title">
      <h2 id="about-title" data-reveal="">Sobre este perfume.</h2>
      <dl className="about-facts" data-reveal="">
        {facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className="num">{v}</dd></div>)}
      </dl>
      <div className="about-ask" data-reveal="">
        <p>No guardamos notas olfativas ni descripciones de las tiendas.</p>
        <Link className="btn-quiet" to={`/match-ia?q=${encodeURIComponent(question)}`}>Pregúntale a Match IA por este perfume</Link>
      </div>
    </section>
  );
}

// La respuesta primero: el más barato de hoy y el botón para ir a esa tienda. Sin precio vigente, lo dice.
function Answer({ prices }) {
  const { cheapest, lowest, stale } = splitPrices(prices);
  if (!prices.length) {
    return <div className="answer"><p className="answer-label">Sin precio</p><p className="answer-none">Hoy ninguna tienda publica este producto.</p></div>;
  }
  if (!cheapest) {
    return (
      <div className="answer">
        <p className="answer-label">Sin precio vigente</p>
        <p className="answer-none">
          {stale.length
            ? "Ninguna tienda con este producto se pudo leer en los últimos 2 días. Abajo están sus últimos precios, con su fecha."
            : "Ninguna tienda lo tiene en stock hoy."}
        </p>
      </div>
    );
  }
  return (
    <div className="answer">
      <p className="answer-label">Más barato hoy</p>
      <p className="answer-price num">{money(lowest)}</p>
      <p className="answer-where">
        en {storeName(cheapest.store)}{perMl(cheapest.price_per_ml) && ` · ${perMl(cheapest.price_per_ml)}`} · {readOn(cheapest.scraped_at)}
      </p>
      <a className="btn btn-buy" href={cheapest.listing_url} target="_blank" rel="noopener noreferrer">
        Ir a {storeName(cheapest.store)}<span className="sr-only"> (abre otra pestaña)</span>
      </a>
    </div>
  );
}

export default function Product() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [retry, setRetry] = useState(0);
  const zoom = useRef(null); // la foto ampliada (celular: se abre al tocar la miniatura)
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
            <Link to="/catalogo" className="btn">Ir al catálogo</Link>
          </div>
        ) : <ErrorMessage error={product.error} onRetry={() => setRetry((n) => n + 1)} />}
      </div>
    );
  }

  const p = product.data;
  const photo = bestImage(p);
  const { cheapest, lowest } = splitPrices(p.prices);
  const facts = [CONCENTRATIONS[p.concentration] ?? "Concentración no informada", PRESENTATIONS[p.presentation]].filter(Boolean);
  return (
    <div className="page">
      <nav className="crumbs" aria-label="Ruta">
        <Link to="/catalogo">Catálogo</Link> › <Link to={`/catalogo?brand=${encodeURIComponent(p.brand)}`}>{p.brand}</Link> ›{" "}
        <span aria-current="page">{nameWithoutBrand(p)}</span>
      </nav>

      <div className="product">
        <div className="stage product-stage"><ProductImage src={photo} alt={p.canonical_name} priority /></div>
        <div className="product-info">
          <div className="product-head">
            {photo ? (
              <button type="button" className="product-thumb" aria-haspopup="dialog" onClick={() => zoom.current?.showModal()}>
                <ProductImage src={photo} /><span className="sr-only">Ampliar la foto de {p.canonical_name}</span>
              </button>
            ) : <div className="product-thumb"><ProductImage /></div>}
            <div>
              <p className="product-brand">{p.brand}</p>
              <h1>{nameWithoutBrand(p)}</h1>
            </div>
          </div>
          <p className="facts">{facts.join(" · ")}</p>
          <Answer prices={p.prices} />
          <PriceLadder prices={p.prices} checks={checks.data?.checks} />
          {p.prices.some((x) => x.is_stale) && (
            <p className="note">Un precio sin lectura reciente se muestra con su fecha y no cuenta para el más barato.</p>
          )}
        </div>
      </div>

      {photo && (
        // Tocar fuera de la foto, el botón o Esc la cierran
        <dialog ref={zoom} className="zoom" aria-label={`Foto de ${p.canonical_name}`}
                onClick={(e) => { if (e.target === zoom.current) zoom.current.close(); }}>
          <div className="zoom-body">
            <ProductImage src={photo} alt={p.canonical_name} />
            <form method="dialog"><button className="btn">Cerrar</button></form>
          </div>
        </dialog>
      )}

      <About product={p} history={history.data} cheapest={cheapest} />

      <section className="panel">
        <h2 data-reveal="">Cómo ha cambiado el precio.</h2>
        <div className="chart-box" data-reveal="">
          {history.loading && <Loading label="Cargando historial…" />}
          {history.error && <ErrorMessage error={history.error} />}
          {history.data && <PriceChart series={history.data.series} prices={p.prices} cheapestUrl={cheapest?.listing_url} />}
        </div>
      </section>

      {variants.data?.items?.length > 0 && (
        <section className="panel">
          <h2 data-reveal="">Otros tamaños y presentaciones.</h2>
          <div className="variants">
            {variants.data.items.map((v) => <ProductCard key={v.product_id} product={v} />)}
          </div>
        </section>
      )}

      {cheapest && (
        <section className="close" data-reveal="">
          <p>El más barato hoy: <strong className="num">{money(lowest)}</strong> en {storeName(cheapest.store)}.</p>
          <a className="btn" href={cheapest.listing_url} target="_blank" rel="noopener noreferrer">
            Ir a {storeName(cheapest.store)}<span className="sr-only"> (abre otra pestaña)</span>
          </a>
        </section>
      )}
    </div>
  );
}
