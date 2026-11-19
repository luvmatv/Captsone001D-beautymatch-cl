import { Suspense, lazy, useEffect, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api.js";
import Header from "./components/Header.jsx";
import Home from "./pages/Home.jsx";
import Catalog from "./pages/Catalog.jsx";
import Offers from "./pages/Offers.jsx";
import Semantic from "./pages/Semantic.jsx";
import Sommelier from "./pages/Sommelier.jsx";
import NotFound from "./pages/NotFound.jsx";
import { Loading } from "./components/Status.jsx";

// La ficha trae la librería de gráficos: se descarga solo al abrir un producto.
const Product = lazy(() => import("./pages/Product.jsx"));

// Aparición al hacer scroll: cada [data-reveal] aparece una vez al entrar en pantalla.
// Lo que ya está a la vista aparece sin transición, y con movimiento reducido todo queda visible.
function useReveal() {
  useEffect(() => {
    document.documentElement.classList.add("js");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const io = "IntersectionObserver" in window && !reduce
      ? new IntersectionObserver((entries) => entries.forEach((e) => {
          if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
        }), { threshold: 0.01 })
      : null;
    const scan = () => document.querySelectorAll("[data-reveal]:not(.in):not(.watched)").forEach((el) => {
      if (!io || el.getBoundingClientRect().top < window.innerHeight) el.classList.add("in", "now");
      else { el.classList.add("watched"); io.observe(el); }
    });
    scan();
    const mo = new MutationObserver(scan);
    mo.observe(document.getElementById("root"), { childList: true, subtree: true });
    return () => { mo.disconnect(); io?.disconnect(); };
  }, []);
}

// Al abrir la página se despierta la API (/healthz). Si tarda más de WAKE_NOTICE_MS (está apagada: la primera
// visita después de un rato espera 25 a 40 s), se avisa hasta que responda. Una API despierta contesta antes
// y el aviso no aparece.
const WAKE_NOTICE_MS = 1500;
function useWakeApi() {
  const [waking, setWaking] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const slow = setTimeout(() => setWaking(true), WAKE_NOTICE_MS);
    api.wake({ signal: controller.signal }).catch(() => {}).finally(() => {
      clearTimeout(slow);
      if (!controller.signal.aborted) setWaking(false);
    });
    return () => { clearTimeout(slow); controller.abort(); };
  }, []);
  return waking;
}

export default function App() {
  useReveal();
  const waking = useWakeApi();
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo({ top: 0 }); }, [pathname]);
  return (
    <>
      <a className="skip" href="#main">Ir al contenido</a>
      <Header />
      <div className="wake" role="status" aria-live="polite">
        {waking && <p><span className="wake-dot" aria-hidden="true" />Despertando el catálogo… la primera visita después de un rato puede tardar hasta un minuto.</p>}
      </div>
      <main id="main">
        <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/catalogo" element={<Catalog />} />
          <Route path="/producto/:id" element={<Product />} />
          <Route path="/ofertas" element={<Offers />} />
          <Route path="/describir" element={<Semantic />} />
          <Route path="/sommelier" element={<Sommelier />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
        </Suspense>
      </main>
      <footer className="site-footer">
        <p>
          BeautyMatch CL compara precios de Preunic, Maicao, Salcobrand, Beauty Perfumes, dperfumes y Dreams Parfums.
          Los precios se leen cada mañana; confirma el valor final en la tienda antes de comprar.
        </p>
        <p>Proyecto Capstone, Ingeniería en Informática, Duoc UC.</p>
      </footer>
    </>
  );
}
