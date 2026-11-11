import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";
import Header from "./components/Header.jsx";
import Catalog from "./pages/Catalog.jsx";
import Offers from "./pages/Offers.jsx";
import Semantic from "./pages/Semantic.jsx";
import NotFound from "./pages/NotFound.jsx";
import { Loading } from "./components/Status.jsx";

// La ficha trae la librería de gráficos: se descarga solo al abrir un producto.
const Product = lazy(() => import("./pages/Product.jsx"));

export default function App() {
  return (
    <>
      <a className="skip" href="#main">Ir al contenido</a>
      <Header />
      <main id="main">
        <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<Catalog />} />
          <Route path="/producto/:id" element={<Product />} />
          <Route path="/ofertas" element={<Offers />} />
          <Route path="/describir" element={<Semantic />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
        </Suspense>
      </main>
      <footer className="site-footer">
        <p>
          BeautyMatch CL compara precios de Preunic, Maicao, Salcobrand, Beauty Perfumes, dperfumes y Dreams Parfums.
          Los precios se actualizan cada mañana; confirma el valor final en la tienda antes de comprar.
        </p>
        <p>Proyecto Capstone, Ingeniería en Informática, Duoc UC.</p>
      </footer>
    </>
  );
}
