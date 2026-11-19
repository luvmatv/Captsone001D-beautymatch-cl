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

El sommelier no está publicado. En desarrollo, la página `/sommelier` usa el de
`http://localhost:8001` si no hay `VITE_SOMMELIER_URL`; se levanta con
`docker compose up` desde la raíz del repo (ver `docs/sommelier.md`). En la
versión publicada (`npm run build`), sin `VITE_SOMMELIER_URL` la página muestra
"Disponible pronto".

La API de Azure se apaga sin tráfico. Al abrir la página se llama a `/healthz`
para despertarla; si tarda más de 1,5 s, aparece "Despertando el catálogo…"
bajo la barra superior hasta que responda.

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

`dist/` es un sitio estático. Es una SPA: cualquier ruta debe devolver
`index.html`, o recargar `/producto/…` daría 404.

### Vercel (proyecto `beautymatch-cl`)

| Campo | Valor |
|---|---|
| Root Directory | `frontend` |
| Framework Preset | Vite |
| Install Command | `npm ci` |
| Build Command | `npm run build` |
| Output Directory | `dist` |
| `VITE_API_URL` (Production) | la URL de la API en Azure |
| `VITE_SOMMELIER_URL` (Production) | la URL del sommelier, cuando se publique |

`vercel.json` (en esta carpeta) manda a `index.html` toda ruta que no sea un
archivo. Las variables `VITE_*` quedan dentro del JavaScript publicado: solo
URLs, nunca claves. El dominio `https://beautymatch-cl.vercel.app` tiene que
estar en `API_CORS_ORIGINS` de la API (y en `SOMMELIER_CORS_ORIGINS` del
sommelier); las vistas previas de Vercel, con otra URL, no reciben datos.
