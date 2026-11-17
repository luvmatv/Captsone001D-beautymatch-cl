---
version: 1
slug: "frontend-src-pages-catalog-jsx"
primary_target: "frontend/src/pages/Catalog.jsx"
related_targets: ["frontend/src/pages/Product.jsx"]
---

# Catálogo y ficha de BeautyMatch CL

Scope: el frontend completo (catálogo, ficha, ofertas, describir, sommelier, 404), modo Operate. Público: compradores en Chile, celular y computador por igual. Tarea: saber en segundos en qué tienda está más barato hoy el mismo perfume y si el dato es reciente. Restricciones: React 18 + Vite + React Router + Recharts; is_stale nunca es "el más barato"; lowest_price e image_url pueden ser null; sin imágenes de relleno; AA, foco visible, teclado; prefers-reduced-motion.

## Direction contract

THESIS: El frasco a contraluz. El precio más bajo de hoy es el único líquido ámbar de la pantalla; el resto es vidrio. Rechaza la tienda de lujo (negro y dorado, serif fina) y la vitrina de descuentos (rojo y amarillo gritando).

OWN-WORLD: Cabecera y barra inferior en verde botella #0F2F29; fondo vidrio marino #EDF3F0; superficies blancas con borde #CFDDD7 y radio 16-20 px; ámbar #F0A93B solo para lo más barato (barra, subrayado del precio, ítem activo); enlaces y foco en #0B5F52; texto #14231F. Funnel Display para títulos y montos, Funnel Sans para el resto, cifras tabulares.

STORY: El comprador busca su perfume, ve en la tarjeta "desde $X en tienda, $/ml", entra a la ficha y lee de inmediato "Más barato hoy: $X en tienda", con la escalera de cada tienda, cuándo se leyó cada precio y los precios viejos aparte. Confía porque nada se presenta como más de lo que los datos dicen.

FIRST VIEWPORT: Catálogo: cabecera verde con logo de dos frascos, título "¿Dónde está más barato tu perfume?", buscador en píldora y, en computador, filtros a la izquierda y grilla de tarjetas blancas; en 375x667 la primera fila de tarjetas con su precio entra completa. Ficha: miniatura o foto, nombre, línea de datos, "Más barato hoy" subrayado en ámbar, escalera con tubos de vidrio y la tienda más barata con líquido ámbar, visible en la primera pantalla del celular.

FORM: Vidrio al trasluz, candidato 3 de 7 de la lista propia (asignado por el sorteo). Movimiento: el líquido llena cada barra una vez al cargar (ease-out, 520 ms, desfase corto), tarjetas suben 2 px al pasar el mouse, presión 0.97 en botones; nada se anima por scroll. seed:fedbab97927cb85e

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
