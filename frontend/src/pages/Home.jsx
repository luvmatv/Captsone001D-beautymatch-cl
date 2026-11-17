import { useState } from "react";
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
    <figcaption className="compare">
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
          {stale.map((x) => `${storeName(x.store)} tenía ${money(x.price)} el ${day(x.scraped_at)}; no la leemos desde entonces y no la comparamos.`).join(" ")}
        </p>
      )}
    </figcaption>
  );
}

function Hero({ product }) {
  const available = product.prices.filter((x) => !x.is_stale && x.is_available).map((x) => x.price);
  const low = available.length ? Math.min(...available) : null;
  const high = available.length ? Math.max(...available) : null;
  return (
    <section className="hero">
      <div className="hero-grid">
        <div>
          <h1>
            {low !== null && high > low
              ? <>{shortName(product)} cuesta <span className="price num">{money(low)}</span> o <span className="num">{money(high)}</span>.</>
              : <>{shortName(product)}, tienda por tienda.</>}
          </h1>
          <p className="hero-sub">Depende de dónde lo compres. Comparamos el mismo frasco en seis tiendas chilenas, cada mañana.</p>
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

export default function Home() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const featured = useApi((opts) => api.featured(opts), []);
  const offers = useApi((opts) => api.offers({ limit: 5 }, opts), []);
  const total = useApi((opts) => api.products({ limit: 1 }, opts), []);
  const go = (q) => navigate(q ? `/catalogo?q=${encodeURIComponent(q)}` : "/catalogo");

  return (
    <div className="home">
      {featured.data ? <Hero product={featured.data} /> : (
        <section className="hero hero-plain">
          <h1>¿Dónde está más barato tu perfume?</h1>
          <p className="hero-sub">Comparamos el mismo frasco en seis tiendas chilenas, cada mañana.</p>
        </section>
      )}

      <section className="search-band">
        <h2 data-reveal="">Busca entre {total.data ? total.data.total.toLocaleString("es-CL") : "miles de"} perfumes.</h2>
        <p data-reveal="">Por nombre, marca o tamaño. Te mostramos el precio de cada tienda y cuándo lo leímos.</p>
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
                extra={<p className="tile-note"><span className="num">−{Math.round(o.discount_percent)}%</span> · el precio tachado coincide con lo que cobraba antes</p>} />
            ))}
          </div>
        </section>
      )}

      <section className="section how">
        <div data-reveal=""><h3>El mismo frasco, de verdad.</h3><p>Unimos dos publicaciones solo si coinciden la fragancia, la concentración, el tamaño y la presentación. Lo dudoso queda fuera.</p></div>
        <div data-reveal=""><h3>Cada precio con su fecha.</h3><p>Leemos las seis tiendas cada mañana. Un precio de hace más de dos días se muestra aparte y nunca cuenta como el más barato.</p></div>
        <div data-reveal=""><h3>Descuentos revisados.</h3><p>Comparamos el precio tachado con lo que la tienda cobraba antes. Si no hay historial suficiente, lo decimos.</p></div>
      </section>
    </div>
  );
}
