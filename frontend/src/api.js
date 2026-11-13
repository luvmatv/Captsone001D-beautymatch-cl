// Cliente de la API de BeautyMatch CL (ver docs/api.md en la raíz del repo).
export const API_URL = (import.meta.env.VITE_API_URL ||
  "https://beautymatch-api.happyrock-538a1151.brazilsouth.azurecontainerapps.io").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(status, detail, extra = {}) {
    super(typeof detail === "string" ? detail : "Parámetro inválido");
    this.status = status;
    this.detail = detail;
    Object.assign(this, extra);
  }
}

function toQuery(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else search.append(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function get(path, params, { signal } = {}) {
  let response;
  try {
    response = await fetch(`${API_URL}${path}${toQuery(params)}`, { signal });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(0, "No se pudo conectar con la API. Revisa tu conexión a internet.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, body?.detail ?? response.statusText, {
      retryAfter: Number(response.headers.get("Retry-After")) || null,
    });
  }
  // fetch sigue solo los 308 de productos fusionados: avisamos el id vigente.
  if (response.redirected) {
    const match = new URL(response.url).pathname.match(/\/products\/([0-9a-f-]{36})/i);
    if (match) body.__movedTo = match[1];
  }
  return body;
}

// Sommelier (agente de IA). Corre aparte de la API, por defecto en el puerto 8001.
export const SOMMELIER_URL = (import.meta.env.VITE_SOMMELIER_URL || "http://localhost:8001").replace(/\/$/, "");

// Envía la conversación completa y devuelve { reply, products, model }.
async function chat(messages, { signal } = {}) {
  let response;
  try {
    response = await fetch(`${SOMMELIER_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(0, "No se pudo conectar con el sommelier. Revisa que esté corriendo.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, body?.detail ?? response.statusText, {
      retryAfter: Number(response.headers.get("Retry-After")) || null,
    });
  }
  return body;
}

export const api = {
  chat,
  products: (params, opts) => get("/products", params, opts),
  product: (id, opts) => get(`/products/${id}`, undefined, opts),
  priceHistory: (id, opts) => get(`/products/${id}/price-history`, undefined, opts),
  listPriceChecks: (id, opts) => get(`/products/${id}/list-price-checks`, undefined, opts),
  variants: (id, opts) => get(`/products/${id}/variants`, undefined, opts),
  brands: (opts) => get("/brands", undefined, opts),
  offers: (params, opts) => get("/offers", params, opts),
  semantic: (params, opts) => get("/search/semantic", params, opts),
};
