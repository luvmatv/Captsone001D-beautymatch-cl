import { Link, NavLink } from "react-router-dom";

export default function Header() {
  return (
    <header className="site-header">
      <Link to="/" className="brand" aria-label="BeautyMatch CL, inicio">
        <svg viewBox="0 0 32 32" aria-hidden="true" className="brand-mark">
          <rect x="12" y="3" width="8" height="5" rx="1.5" fill="currentColor" />
          <rect x="6" y="9" width="20" height="20" rx="6" fill="#C98A00" />
          <rect x="10" y="14" width="4" height="10" rx="2" fill="#fff" opacity=".55" />
        </svg>
        <span>BeautyMatch<span className="brand-cl">CL</span></span>
      </Link>
      <nav aria-label="Principal">
        <NavLink to="/" end>Catálogo</NavLink>
        <NavLink to="/ofertas">Ofertas reales</NavLink>
        <NavLink to="/describir">Buscar por descripción</NavLink>
        <NavLink to="/sommelier">Sommelier</NavLink>
      </nav>
    </header>
  );
}
