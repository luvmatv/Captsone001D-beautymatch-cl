import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { bestImage, day, money, readOn, shortName, storeName } from "../format.js";
import { useApi } from "../useApi.js";
import ProductCard, { ProductImage } from "../components/ProductCard.jsx";

// Perfume destacado de la portada: lo elige la API (GET /featured). Lattafa Yara si tiene precio vigente
// con stock en 3 tiendas o más y buena foto; si no, el que está en más tiendas y luego con más diferencia.
// Si ninguno cumple (404), la portada abre con un titular sin producto.

// Comparación del destacado: solo precios vigentes y con stock compiten; los viejos se nombran aparte.
function Compare({ product }) {
  const fresh = product.prices.filter((x) => !x.is_stale);
  const stale = product.prices.filter((x) => x.is_stale);
  const available = fresh.filter((x) => x.is_available);
  const lowest = available.length ? Math.min(...available.map((x) => x.price)) : null;
  const scale = Math.max(...product.prices.map((x) => x.price));
  const reads = [...new Set(fresh.map((x) => readOn(x.scraped_at).replace("leído ", "")))];
  return (
    <figcaption className="compare" data-fill="">
      <div className="compare-head">
        <strong>{product.canonical_name}</strong>
        <span>{fresh.length} {fresh.length === 1 ? "tienda" : "tiendas"}{reads.length > 0 && ` · leído ${reads.join(" y ")}`}</span>
      </div>
      <ol className="bars">
        {fresh.map((x, i) => {
          const isLowest = x.is_available && x.price === lowest;
          return (
            <li key={x.listing_url} className={`bar${isLowest ? " lowest" : ""}`} style={{ "--i": i }}>
              <span className="bar-store">{storeName(x.store)}</span>
              <span className="bar-track" aria-hidden="true"><span className="bar-fill" style={{ "--w": `${(x.price / scale) * 100}%` }} /></span>
              <span className="bar-price num">{x.is_available ? money(x.price) : "Sin stock"}</span>
            </li>
          );
        })}
      </ol>
      {stale.length > 0 && (
        <p className="compare-foot">
          {stale.map((x) => `${storeName(x.store)} no se compara: su último precio es del ${day(x.scraped_at)}.`).join(" ")}
        </p>
      )}
    </figcaption>
  );
}

// Número que cuenta hacia arriba una sola vez (400 ms, ease-out). El valor final ocupa su lugar desde el
// principio (capa invisible), así el titular no cambia de ancho mientras cuenta; los lectores de pantalla
// leen solo el valor final.
function CountUp({ value, format }) {
  const [shown, setShown] = useState(() =>
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? value : 0);
  useEffect(() => {
    if (shown === value) return;
    let frame;
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / 400);
      setShown(Math.round(value * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <span className="count num">
      <span className="count-ghost" aria-hidden="true">{format(value)}</span>
      <span className="count-live" aria-hidden="true">{format(shown)}</span>
      <span className="sr-only">{format(value)}</span>
    </span>
  );
}

// Titular de ahorro, armado con los precios vigentes y con stock de /featured: la diferencia entre la tienda
// más cara y la más barata. Con una sola tienda (o todas al mismo precio) no hay ahorro que anunciar.
function Hero({ product }) {
  const { available, lowest, cheapest } = (() => {
    const list = product.prices.filter((x) => !x.is_stale && x.is_available);
    const low = list.length ? Math.min(...list.map((x) => x.price)) : null;
    return { available: list, lowest: low, cheapest: list.find((x) => x.price === low) };
  })();
  const highest = available.length ? Math.max(...available.map((x) => x.price)) : null;
  const saving = lowest !== null && highest > lowest ? highest - lowest : null;
  const stores = new Set(available.map((x) => x.store)).size;
  return (
    <section className="hero">
      <div className="hero-grid">
        <div>
          <h1>
            {saving
              ? <>Ahorra <CountUp value={saving} format={money} /> en {shortName(product)}</>
              : <>{shortName(product)}, tienda por tienda</>}
          </h1>
          <p className="hero-sub">
            {cheapest ? <>
              {stores > 1 ? `El mismo perfume en ${stores} tiendas. ` : ""}
              Lo más barato hoy: <strong className="hero-low num">{money(lowest)}</strong> en {storeName(cheapest.store)}.
            </> : "Comparamos el mismo frasco en seis tiendas chilenas, cada mañana."}
          </p>
          <div className="hero-actions">
            <Link className="btn" to={`/producto/${product.product_id}`}>Ver la comparación</Link>
            <Link className="link-arrow" to="/catalogo">Explorar el catálogo</Link>
          </div>
        </div>
        <figure className="stage hero-stage">
          <ProductImage src={bestImage(product)} alt={product.canonical_name} priority />
          <Compare product={product} />
        </figure>
      </div>
    </section>
  );
}

// Mientras llega /featured: el mismo espacio que ocupará el destacado, para que nada salte al cargar.
function HeroWaiting() {
  return (
    <section className="hero hero-waiting" aria-busy="true" aria-label="Cargando el perfume destacado">
      <div className="hero-grid">
        <div>
          <span className="ghost-line" style={{ width: "86%" }} />
          <span className="ghost-line" style={{ width: "58%" }} />
          <span className="ghost-text" />
          <span className="ghost-text" style={{ width: "70%" }} />
        </div>
        <div className="stage hero-stage" />
      </div>
    </section>
  );
}

export default function Home() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const featured = useApi((opts) => api.featured(opts), []);
  const offers = useApi((opts) => api.offers({ limit: 5 }, opts), []);
  const total = useApi((opts) => api.products({ limit: 1 }, opts), []);
  const go = (q) => navigate(q ? `/catalogo?q=${encodeURIComponent(q)}` : "/catalogo");

  return (
    <div className="home">
      {featured.data ? <Hero product={featured.data} /> : featured.loading ? <HeroWaiting /> : (
        <section className="hero hero-plain">
          <h1>¿Dónde está más barato tu perfume?</h1>
          <p className="hero-sub">Comparamos el mismo frasco en seis tiendas chilenas, cada mañana.</p>
        </section>
      )}

      <section className="search-band">
        <h2 data-reveal="">Busca entre {total.data ? total.data.total.toLocaleString("es-CL") : "miles de"} perfumes.</h2>
        <p data-reveal="">Por nombre, marca o tamaño. Verás el precio de cada tienda y cuándo lo leímos.</p>
        <form className="search" role="search" data-reveal="" onSubmit={(e) => { e.preventDefault(); go(text.trim()); }}>
          <label htmlFor="home-q" className="sr-only">Buscar perfume o marca</label>
          <input id="home-q" type="search" value={text} maxLength={100} autoComplete="off"
                 placeholder="Busca un perfume o una marca" onChange={(e) => setText(e.target.value)} />
          <button type="submit" aria-label="Buscar">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></svg>
          </button>
        </form>
        <p className="brands" data-reveal="">
          Lo más buscado:{" "}
          {["Lattafa", "Carolina Herrera", "Antonio Banderas", "Paco Rabanne"].map((b) => (
            <Link key={b} to={`/catalogo?brand=${encodeURIComponent(b)}`}>{b}</Link>
          ))}
        </p>
      </section>

      {offers.data?.items.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h2 data-reveal="">Descuentos que revisamos hoy.</h2>
            <Link className="link-arrow" to="/ofertas">Ver las {offers.data.total} ofertas</Link>
          </div>
          <div className="offers">
            {offers.data.items.map((o) => (
              <ProductCard key={o.listing_url} from={false}
                product={{ ...o, lowest_price: o.price, lowest_price_store: o.store, price_per_ml: null }}
                extra={<p className="tile-note"><span className="num">−{Math.round(o.discount_percent)}%</span> · precio tachado comprobado</p>} />
            ))}
          </div>
        </section>
      )}

      <section className="section how">
        <div data-reveal=""><h3>El mismo frasco, de verdad.</h3><p>Solo juntamos publicaciones con la misma fragancia, concentración, tamaño y presentación. Si hay dudas, no las juntamos.</p></div>
        <div data-reveal=""><h3>Cada precio con su fecha.</h3><p>Leemos las seis tiendas cada mañana. Un precio de hace más de dos días va aparte y no cuenta como el más barato.</p></div>
        <div data-reveal=""><h3>Descuentos revisados.</h3><p>Comparamos el precio tachado con lo que la tienda cobraba antes. Si falta historial, lo decimos.</p></div>
      </section>
    </div>
  );
}
