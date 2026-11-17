import { useState } from "react";
import { Link } from "react-router-dom";
import { CONCENTRATION_SHORT, PRESENTATIONS, bigImage, money, nameWithoutBrand, perMl, readOn, storeName } from "../format.js";

// Frasco dibujado para productos sin foto de ninguna tienda o con una foto que no carga.
export function Bottle() {
  return (
    <svg viewBox="0 0 64 84" className="bottle" role="img" aria-label="Sin foto de la tienda">
      <rect x="24" y="4" width="16" height="10" rx="3" />
      <rect x="11" y="18" width="42" height="60" rx="16" />
      <path d="M22 52h20" />
    </svg>
  );
}

// La foto de la tienda, o el frasco genérico si no hay foto o si no carga (las tiendas cambian sus URLs).
export function ProductImage({ src, alt = "", lazy = false, priority = false }) {
  const [failed, setFailed] = useState(null);
  const url = bigImage(src);
  if (!url || failed === url) return <Bottle />;
  return <img src={url} alt={alt} loading={lazy ? "lazy" : undefined} fetchpriority={priority ? "high" : undefined}
              onError={() => setFailed(url)} />;
}

// Firma de la tarjeta: en cuántas tiendas está con precio vigente y hasta cuánto cobran (store_count, highest_price).
function Spread({ product }) {
  const { store_count: count, highest_price: top, lowest_price: low, lowest_price_store: store } = product;
  if (!count || low == null) return null;
  if (count === 1) return <p className="spread">Solo en {storeName(store)}</p>;
  return (
    <p className="spread">
      <span className="spread-bar" aria-hidden="true"><i style={{ "--lo": `${(low / top) * 100}%` }} /></span>
      <span>{count} tiendas · hasta <span className="num">{money(top)}</span></span>
    </p>
  );
}

export default function ProductCard({ product, extra, from = true }) {
  const tags = [
    product.concentration && CONCENTRATION_SHORT[product.concentration],
    product.volume_ml && `${product.volume_ml} ml`,
    product.presentation && product.presentation !== "full_bottle" && PRESENTATIONS[product.presentation],
  ].filter(Boolean);
  const hasPrice = product.lowest_price !== null && product.lowest_price !== undefined;
  return (
    <Link to={`/producto/${product.product_id}`} className="tile" data-reveal="">
      <div className="tile-stage"><ProductImage src={product.image_url} lazy /></div>
      <div className="tile-body">
        <p className="tile-brand">{product.brand}</p>
        <h3 className="tile-name">{nameWithoutBrand(product)}</h3>
        {tags.length > 0 && <p className="tile-brand">{tags.join(" · ")}</p>}
        {extra}
        {hasPrice ? (
          <>
            <p className="tile-price">
              {from && <span className="muted">desde </span>}<strong className="num">{money(product.lowest_price)}</strong>
              {product.lowest_price_store && <span className="where"> en {storeName(product.lowest_price_store)}</span>}
            </p>
            {perMl(product.price_per_ml) && <p className="where num">{perMl(product.price_per_ml)}</p>}
          </>
        ) : product.last_known_price != null ? (
          // Sin precio vigente: el último que conocemos, con su tienda y su fecha; nunca como "desde".
          <>
            <p className="tile-price none">Último precio <span className="num">{money(product.last_known_price)}</span>
              {product.last_known_price_store && <span className="where"> en {storeName(product.last_known_price_store)}</span>}
            </p>
            <p className="where">{readOn(product.last_known_price_at)} · sin lectura reciente</p>
          </>
        ) : (
          <>
            <p className="tile-price none">Sin precio vigente</p>
            <p className="where">Ninguna tienda leída en los últimos 2 días</p>
          </>
        )}
        {from && <Spread product={product} />}
      </div>
    </Link>
  );
}
