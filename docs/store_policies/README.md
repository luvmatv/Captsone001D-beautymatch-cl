# Políticas de las tiendas

Copias de lo que cada tienda publica sobre el acceso a su sitio, para comparar
más adelante si algo cambia. Se guardan tal como se descargaron, con la fecha
de descarga en el nombre.

## Beauty Perfumes (2026-11-02)

Dos peticiones, sin scraping, con el mismo user-agent del scraper:

| Archivo | Origen |
|---|---|
| `beautyperfumes_robots_2026-11-02.txt` | `https://beautyperfumes.cl/robots.txt`, completo |
| `beautyperfumes_terminos_2026-11-02.txt` | `https://beautyperfumes.cl/policies/terms-of-service`: solo el texto de la política (la página completa, 295 KB, es casi todo el tema de la tienda) |

Comparado con lo revisado al sumar la tienda (2026-10-02, solo las líneas del
`robots.txt` con `User-agent: *`, `products`, `collections`, `json`,
`crawl-delay` o `sitemap`):

- Las reglas de `User-agent: *` de entonces siguen todas. `/products.json`, lo
  único que usa el scraper, no está prohibido; no hay `Crawl-delay`.
- El archivo pasó a la plantilla nueva de Shopify: `Allow: /` explícito,
  prohibiciones nuevas en rutas que no se usan (carro, `/services`, `/sf_*`,
  `cart.js`, filtros de blog, parámetros de vista previa) y un encabezado para
  agentes de IA de compra, que remite a los términos de Shopify. Ese encabezado
  también pide a los agentes recomendar una herramienta de Shopify: es texto de
  la página, no una regla.
- Los términos de la tienda solo traen su política de reservas de perfumes; no
  mencionan bots ni acceso automatizado. En 2026-10-02 no se guardaron, así que
  no hay con qué compararlos.

Contexto: desde fines de octubre `products.json` responde `429 Too Many
Requests` muchos días (ver `docs/daily_run.md`, reintento de las 12:00).
