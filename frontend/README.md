# Frontend de BeautyMatch CL

React + Vite. Usa la API publicada en Azure, así que **no hace falta levantar
el backend** para trabajar en el frontend.

## Correrlo

Requisito: Node.js 18 o superior.

```powershell
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run dev:3000     # o en http://localhost:3000
```

La API solo acepta llamadas del navegador desde los puertos 5173 y 3000 (CORS).
Cuando el frontend se publique, hay que pedir que agreguen su URL a
`API_CORS_ORIGINS`.

Para usar otra API (por ejemplo la local en `http://127.0.0.1:8000`), copia
`.env.example` a `.env` y cambia `VITE_API_URL`.

El sommelier no está publicado: la página `/sommelier` usa el de
`http://localhost:8001` (`VITE_SOMMELIER_URL`). Se levanta con
`docker compose up` desde la raíz del repo (ver `docs/sommelier.md`).

## Páginas

| Ruta | Qué muestra | Endpoints |
|---|---|---|
| `/` | Buscador, filtros (marca, precio, género, concentración, tamaño, tienda), orden y paginación. Los filtros quedan en la URL | `GET /products`, `GET /brands` |
| `/producto/:id` | Precio en cada tienda, si los descuentos son reales, historial y otros tamaños | `GET /products/{id}`, `/price-history`, `/list-price-checks`, `/variants` |
| `/ofertas` | Descuentos con precio tachado respaldado por el historial | `GET /offers` |
| `/describir` | Búsqueda en lenguaje natural ("perfume árabe de vainilla") | `GET /search/semantic` |
| `/sommelier` | Chat con el sommelier (agente de IA) que recomienda perfumes del catálogo | `POST /chat` del sommelier (puerto 8001) |

Si un producto se fusionó con otro, la API redirige (308) y la ficha cambia la
URL al id vigente. Mientras el modelo de búsqueda semántica carga (503 con
`Retry-After`), la página reintenta sola.

## Estructura

```
src/
  api.js          cliente de la API (URL, errores, redirecciones)
  format.js       precios CLP, fechas, nombres de tiendas y etiquetas
  useApi.js       hook para llamar a la API y cancelar llamadas viejas
  useFilters.js   filtros guardados en la URL
  components/     cabecera, tarjeta, filtros, escalera de precios, gráfico
  pages/          Catalog, Product, Offers, Semantic, Sommelier, NotFound
  styles.css      todos los estilos (variables de color y tipografía arriba)
```

## Publicar

```powershell
npm run build        # deja el sitio en dist/
```

`dist/` es un sitio estático (sirve Azure Static Web Apps, Netlify o Vercel).
Es una SPA: configura el hosting para que cualquier ruta devuelva `index.html`.
