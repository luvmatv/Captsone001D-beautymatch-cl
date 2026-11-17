import { Link, NavLink } from "react-router-dom";

// Logo "Frasco igual": un frasco con el signo igual en negativo (el mismo producto en cada tienda).
export function LogoMark({ className }) {
  return (
    <svg viewBox="0 0 20 30" className={className} aria-hidden="true">
      <rect x="5.5" y="1" width="9" height="4.5" rx="1.6" className="logo-cap" />
      <rect x="1" y="7" width="18" height="22" rx="6" fill="currentColor" />
      <rect x="5" y="14" width="10" height="2.6" rx="1.3" className="logo-cut" />
      <rect x="5" y="19.4" width="10" height="2.6" rx="1.3" className="logo-cut" />
    </svg>
  );
}

// Íconos de la barra inferior del celular. Trazo de 1.7, 24x24.
const ICONS = {
  home: <path d="M4 11 12 4l8 7v8.5a1 1 0 0 1-1 1h-4.5V15h-5v5.5H5a1 1 0 0 1-1-1Z" />,
  catalog: (
    <>
      <rect x="4" y="4" width="7" height="7" rx="2" /><rect x="13" y="4" width="7" height="7" rx="2" />
      <rect x="4" y="13" width="7" height="7" rx="2" /><rect x="13" y="13" width="7" height="7" rx="2" />
    </>
  ),
  offers: (
    <>
      <path d="M3.5 12.6V5.5a2 2 0 0 1 2-2h7.1a2 2 0 0 1 1.4.6l6.5 6.5a2 2 0 0 1 0 2.8l-7.1 7.1a2 2 0 0 1-2.8 0L4.1 14a2 2 0 0 1-.6-1.4Z" />
      <circle cx="8.5" cy="8.5" r="1.4" />
    </>
  ),
  describe: <><path d="M4 6h9M4 10.5h6M4 15h4" /><circle cx="15.5" cy="14.5" r="3.8" /><path d="m18.3 17.3 2.7 2.7" /></>,
  sommelier: <path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v8.5a1.5 1.5 0 0 1-1.5 1.5h-7l-4.5 3.5V16.5H5A1.5 1.5 0 0 1 3.5 15V6.5A1.5 1.5 0 0 1 5 5Z" />,
};
const ITEMS = [
  ["/", "home", "Inicio", "Inicio", true],
  ["/catalogo", "catalog", "Catálogo", "Catálogo"],
  ["/ofertas", "offers", "Ofertas reales", "Ofertas"],
  ["/describir", "describe", "Buscar por descripción", "Describir"],
  ["/sommelier", "sommelier", "Sommelier", "Sommelier"],
];
const Items = () => ITEMS.map(([to, icon, long, short, end]) => (
  <NavLink key={to} to={to} end={end} className="nav-item">
    <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{ICONS[icon]}</svg>
    <span className="nav-long">{long}</span>
    <span className="nav-short">{short}</span>
  </NavLink>
));

// Arriba, barra translúcida con el logo y las secciones; en celular las secciones pasan a una barra fija abajo.
// La barra de abajo va fuera del header: el backdrop-filter del header atraparía su position: fixed.
export default function Header() {
  return (
    <>
      <header className="site-header">
        <div className="header-row">
          <Link to="/" className="brand" aria-label="BeautyMatch CL, inicio">
            <LogoMark className="brand-mark" />
            <span className="brand-word">BeautyMatch<span className="brand-cl">CL</span></span>
          </Link>
          <nav aria-label="Principal" className="topnav"><Items /></nav>
        </div>
      </header>
      <nav aria-label="Secciones" className="tabbar"><Items /></nav>
    </>
  );
}
