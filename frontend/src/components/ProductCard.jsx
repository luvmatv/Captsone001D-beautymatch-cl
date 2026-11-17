import { useState } from "react";
import { Link } from "react-router-dom";
import { CONCENTRATION_SHORT, PRESENTATIONS, money, perMl, storeName } from "../format.js";

export function Bottle() {
  // Para productos sin imagen (Maicao no entrega imágenes).
  return (
    <svg viewBox="0 0 64 80" className="bottle" aria-hidden="true">
      <rect x="24" y="4" width="16" height="12" rx="3" />
      <rect x="10" y="20" width="44" height="56" rx="14" />
    </svg>
  );
}

// La foto de la tienda, o el frasco genérico si no hay foto o si no carga (las tiendas cambian sus URLs).
export function ProductImage({ src, alt = "", lazy = false }) {
  const [failed, setFailed] = useState(null);
  if (!src || failed === src) return <Bottle />;
  return <img src={src} alt={alt} loading={lazy ? "lazy" : undefined} onError={() => setFailed(src)} />;
}

export default function ProductCard({ product, extra }) {
  const tags = [
    product.concentration && CONCENTRATION_SHORT[product.concentration],
    product.volume_ml && `${product.volume_ml} ml`,
    product.presentation && product.presentation !== "full_bottle" && PRESENTATIONS[product.presentation],
  ].filter(Boolean);
  return (
    <article className="card">
      <Link to={`/producto/${product.product_id}`} className="card-link">
        <div className="card-image">
          <ProductImage src={product.image_url} lazy />
          {product.best_discount_percent > 0 && (
            <span className="badge">-{Math.round(product.best_discount_percent)}%</span>
          )}
        </div>
        <div className="card-body">
          <p className="card-brand">{product.brand}</p>
          <h3 className="card-name">{product.canonical_name}</h3>
          <p className="card-tags">{tags.join(", ")}</p>
          <p className="card-price">
            {product.lowest_price !== null && <span className="from">desde</span>}
            <strong>{money(product.lowest_price)}</strong>
          </p>
          {product.lowest_price_store && (
            <p className="card-store">
              en {storeName(product.lowest_price_store)}
              {perMl(product.price_per_ml) && <span className="muted">{" "}({perMl(product.price_per_ml)})</span>}
            </p>
          )}
          {extra}
        </div>
      </Link>
    </article>
  );
}
