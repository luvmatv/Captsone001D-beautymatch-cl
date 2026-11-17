import { Link, NavLink } from "react-router-dom";

// Íconos del menú: solo se ven en la barra inferior del celular (bajo 520 px). Trazo de 1.8, 24x24.
const ICONS = {
  catalog: (
    <>
      <rect x="4" y="4" width="7" height="7" rx="2" />
      <rect x="13" y="4" width="7" height="7" rx="2" />
      <rect x="4" y="13" width="7" height="7" rx="2" />
      <rect x="13" y="13" width="7" height="7" rx="2" />
    </>
  ),
  offers: (
    <>
      <path d="M3.5 12.6V5.5a2 2 0 0 1 2-2h7.1a2 2 0 0 1 1.4.6l6.5 6.5a2 2 0 0 1 0 2.8l-7.1 7.1a2 2 0 0 1-2.8 0L4.1 14a2 2 0 0 1-.6-1.4Z" />
      <circle cx="8.5" cy="8.5" r="1.4" />
    </>
  ),
  describe: (
    <>
      <path d="M4 6h9M4 10.5h6M4 15h4" />
      <circle cx="15.5" cy="14.5" r="3.8" />
      <path d="m18.3 17.3 2.7 2.7" />
    </>
  ),
  sommelier: (
    <>
      <path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v8.5a1.5 1.5 0 0 1-1.5 1.5h-7l-4.5 3.5V16.5H5A1.5 1.5 0 0 1 3.5 15V6.5A1.5 1.5 0 0 1 5 5Z" />
      <path d="M8.5 9.5h7M8.5 12.5h4.5" />
    </>
  ),
};

function Item({ to, icon, long, short, end }) {
  return (
    <NavLink to={to} end={end}>
      <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{ICONS[icon]}</svg>
      <span className="nav-long">{long}</span>
      <span className="nav-short">{short}</span>
    </NavLink>
  );
}

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
        <Item to="/" end icon="catalog" long="Catálogo" short="Catálogo" />
        <Item to="/ofertas" icon="offers" long="Ofertas reales" short="Ofertas" />
        <Item to="/describir" icon="describe" long="Buscar por descripción" short="Describir" />
        <Item to="/sommelier" icon="sommelier" long="Sommelier" short="Sommelier" />
      </nav>
    </header>
  );
}
