# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Compradores en Chile que quieren comprar un perfume (o colonia, body mist, splash, estuche) y buscan en qué tienda online está más barato hoy, y si el descuento que muestra la tienda es real. Lo usan tanto desde el celular como desde el computador. La presentación del Capstone (Duoc UC) es una demostración de ese mismo uso, no un público aparte.

## Product Purpose

BeautyMatch CL compara precios de perfumería entre seis tiendas chilenas: Preunic, Maicao, Salcobrand, Beauty Perfumes, dperfumes y Dreams Parfums. Cada tienda publica el mismo producto con nombres distintos; BeautyMatch reconoce cuáles publicaciones son el mismo producto (misma fragancia, concentración, volumen y presentación) y muestra en una ficha consolidada el precio de cada tienda, el más barato y el historial. Éxito: el comprador sabe en segundos dónde comprar y confía en que la comparación es del mismo producto.

## Positioning

La precisión del emparejamiento: unir dos productos distintos se considera peor que perder un match, cada regla se mide contra etiquetas humanas y lo dudoso queda fuera de la comparación. Además, los precios de lista se verifican contra el historial de cada publicación y contra las otras tiendas.

## Operating Context

- Los datos vienen de una corrida diaria (09:00, hora de Chile) que scrapea las seis tiendas; algunas tiendas a veces se leen parcialmente o no se leen un día.
- El frontend consume la API FastAPI publicada en Azure Container Apps; la base está en Neon (plan gratis, transferencia mensual limitada).
- Además del catálogo y la ficha hay: ofertas, búsqueda semántica y un sommelier (chat con Gemini que recomienda perfumes del catálogo).

## Capabilities and Constraints

- Stack fijo: React 18 + Vite + React Router + Recharts, en `frontend/`. No migrar a Next.js ni a Tailwind.
- Un precio leído hace más de 2 días viene con `is_stale` y su fecha: nunca se presenta como "el más barato" ni cuenta para ofertas.
- `lowest_price` puede venir `null` (ningún precio vigente) y `image_url` puede venir `null`.
- La verificación de precio de lista responde "sin datos suficientes" cuando falta historial. Nunca se llama "ficticio" a un descuento: se nombra por lo que mide.
- La API gasta transferencia de Neon: el frontend no debe consultarla en bucle.
- Fuera del alcance: compra o checkout, app nativa, autenticidad del producto, otras categorías de belleza.

## Brand Commitments

Solo el nombre "BeautyMatch CL". Sin logo, colores, tipografía ni tono fijados: lo visual actual se puede cambiar. La interfaz está en español de Chile.

## Evidence on Hand

- Datos reales del catálogo vía la API (miles de publicaciones, seis tiendas, historial diario desde octubre de 2026).
- Precisión del emparejamiento registrada en `docs/matching_evaluation.md`.
- No hay testimonios, usuarios ni cifras de uso: no inventarlos.

## Product Principles

1. Exactitud antes que atractivo: nunca mostrar como comparable o "más barato" algo que los datos no respaldan.
2. Mostrar la antigüedad del dato: el comprador debe saber cuándo se leyó cada precio.
3. La respuesta primero: dónde está más barato hoy, a la vista sin buscarla.
4. Igual de usable en celular que en computador.
