# Sommelier (agente de IA)

Un chat que recomienda perfumes como lo haría un vendedor experto, y dice dónde
comprarlos al mejor precio. Usa **Gemini** (plan gratuito de Google AI Studio)
y lee el catálogo **solo a través de la API de BeautyMatch**, así que todo
producto, precio y tienda que menciona sale de la base.

```
Frontend (5173) ──POST /chat──▶ Sommelier (8001) ──▶ Gemini
                                     │
                                     └──GET──▶ API (8000) ──▶ PostgreSQL bm-pg (5432)
```

## Cómo funciona

El modelo recibe la conversación y cinco herramientas, que son llamadas `GET` a
la API (`src/sommelier/catalog.py`):

| Herramienta | Endpoint | Para qué |
|---|---|---|
| `buscar_por_descripcion` | `GET /search/semantic` | "algo dulce de vainilla", nombres mal escritos |
| `buscar_productos` | `GET /products` | un perfume por nombre, una marca, lo más barato bajo un presupuesto |
| `ver_producto` | `GET /products/{id}` | precio en cada tienda y link de compra |
| `ver_variantes` | `GET /products/{id}/variants` | otros tamaños y sets de la misma fragancia |
| `ver_ofertas` | `GET /offers` | descuentos verificados con el historial |

El agente (`src/sommelier/agent.py`) deja que el modelo llame herramientas
hasta 6 rondas y devuelve la respuesta más los productos del catálogo que esa
respuesta nombra (para mostrarlos como tarjetas).

**Límite importante:** la base solo tiene nombre, marca, concentración, volumen
y precios; **no tiene notas olfativas**. Las notas y "perfumes parecidos" salen
del conocimiento general de Gemini, y el prompt le pide decirlo cuando no está
seguro. La búsqueda semántica compara con nombres, por eso el prompt le pide
pensar primero en perfumes concretos y buscarlos por nombre.

## Ponerlo a andar

1. **API key de Gemini** (gratis, sin tarjeta): https://aistudio.google.com/apikey.
   Agregarla al `.env` de la raíz (nunca se sube a git):

   ```
   GEMINI_API_KEY=tu_key
   ```

   El plan gratuito tiene límites de solicitudes por minuto y **por día, por
   modelo** (ver https://ai.dev/rate-limit), y cada mensaje del chat gasta 2 a 4
   solicitudes (una por cada ronda de búsquedas). Por eso `GEMINI_MODEL` es una
   lista: cuando un modelo responde `429` (cuota agotada) o rechaza la key, el
   sommelier usa el siguiente y vuelve a probar el primero una hora después. Si
   se agotan todos, `/chat` responde `503` con `Retry-After`. En el plan
   gratuito Google puede usar los mensajes para mejorar sus modelos.

   Google retira modelos seguido: si uno responde `404`, se salta solo, pero
   conviene actualizar la lista con los que muestra AI Studio.

2. **Base de datos**: el contenedor `bm-pg` con datos (README).

   ```powershell
   docker start bm-pg
   ```

3. **Frontend, API y sommelier en Docker**:

   ```powershell
   docker compose up --build -d
   ```

   - Frontend: http://localhost:5173 (el chat está en http://localhost:5173/sommelier)
   - API: http://localhost:8000/docs
   - Sommelier: http://localhost:8001/docs, salud en http://localhost:8001/healthz
   - La API tarda ~30 s en cargar el modelo de embeddings; el sommelier parte
     cuando la API responde. El frontend instala sus dependencias la primera vez (~1 min).
   - Si ya hay una API corriendo con `uvicorn` en el 8000, hay que detenerla antes.

   Sin Docker (desarrollo):

   ```powershell
   uvicorn src.api.main:app --env-file .env --port 8000
   uvicorn src.sommelier.main:app --env-file .env --port 8001
   ```

### Variables

| Variable | Por defecto | Qué es |
|---|---|---|
| `GEMINI_API_KEY` | — | Obligatoria para conversar; sin ella `/chat` responde `503` |
| `GEMINI_MODEL` | `gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite` | Modelos de Gemini en orden de preferencia (ver arriba) |
| `CATALOG_API_URL` | `http://localhost:8000` | La API (en Docker, `http://api:8000`) |
| `SOMMELIER_CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Orígenes del navegador permitidos, separados por comas |

## Para el frontend: `POST /chat`

La página `/sommelier` del frontend (`frontend/src/pages/Sommelier.jsx`) ya lo
usa. La URL se configura con `VITE_SOMMELIER_URL` (por defecto
`http://localhost:8001`).

El servicio no guarda conversaciones: el frontend manda **todo el historial**
cada vez (máximo 30 mensajes de hasta 2.000 caracteres; el último, del usuario).

```js
const response = await fetch("http://localhost:8001/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    messages: [
      { role: "user", content: "Busco algo dulce para mujer, hasta 30 mil" },
    ],
  }),
});
const { reply, products } = await response.json();
// después: messages.push({ role: "assistant", content: reply })
```

Respuesta:

```json
{
  "reply": "Te recomiendo **Plaisance Hot Vainilla EDP 100 ml**, a $13.999 en Preunic: ...",
  "products": [
    { "product_id": "…", "canonical_name": "Plaisance Hot Vainilla EDP 100 ml", "brand": "Plaisance",
      "concentration": "edp", "volume_ml": 100, "presentation": "full_bottle", "lowest_price": 13999,
      "lowest_price_store": "preunic", "image_url": "https://…", "price_per_ml": 139.99,
      "best_discount_percent": null }
  ],
  "model": "gemini-3.6-flash"
}
```

- `reply` viene en Markdown simple (negritas y listas con guiones).
- `products` tiene los mismos campos que un producto de `GET /products`, así
  que se muestra con el mismo componente `ProductCard`.
- Errores: `422` si el cuerpo no es válido o el último mensaje no es del
  usuario; `503` (con `Retry-After`) si Gemini no está disponible, se acabó la
  cuota o falta la API key.

## Tests

```powershell
python -m pytest tests/sommelier
```

Usan un modelo falso y una API falsa: no llaman a Gemini ni necesitan la base.
