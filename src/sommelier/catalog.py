"""Herramientas del sommelier: consultas de solo lectura a la API de BeautyMatch.

Cada herramienta tiene nombre, descripción y esquema JSON para el modelo, y una
función que llama a la API y devuelve solo los campos necesarios, con los
precios ya formateados. Si la API falla, se devuelve {"error": ...} al modelo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

STORE_NAMES = {
    "preunic": "Preunic",
    "maicao": "Maicao",
    "salcobrand": "Salcobrand",
    "beautyperfumes": "Beauty Perfumes",
    "dperfumes": "dperfumes",
    "dreamsparfums": "Dreams Parfums",
}
CONCENTRATIONS = ["edp", "edt", "parfum", "cologne", "eau_fraiche", "other"]
GENDERS = ["male", "female", "unisex"]
SORTS = ["relevance", "name", "price_asc", "price_desc", "discount", "price_per_ml"]
MAX_RESULTS = 15


def clp(value: int | float | None) -> str | None:
    """Formatea pesos chilenos: 25999 -> "$25.999"."""
    return None if value is None else "$" + f"{round(value):,}".replace(",", ".")


def store_name(store: str | None) -> str | None:
    return None if store is None else STORE_NAMES.get(store, store)


def summary(item: dict) -> dict:
    """Resumen de un producto con los campos que necesita el modelo."""
    out = {
        "product_id": item["product_id"],
        "nombre": item["canonical_name"],
        "marca": item["brand"],
        "concentracion": item.get("concentration"),
        "volumen_ml": item.get("volume_ml"),
        "presentacion": item.get("presentation"),
        "precio_mas_bajo": clp(item.get("lowest_price")),
        "tienda_mas_barata": store_name(item.get("lowest_price_store")),
    }
    if item.get("best_discount_percent"):
        out["mejor_descuento_pct"] = item["best_discount_percent"]
    if item.get("similarity") is not None:
        out["similitud"] = round(item["similarity"], 3)
    if item.get("lowest_price") is None:
        out["nota"] = "sin precio disponible hoy"
    return out


# Filtros comunes a las herramientas de búsqueda

FILTERS: dict[str, Any] = {
    "precio_min": {"type": "integer", "description": "Precio mínimo en pesos chilenos (CLP)."},
    "precio_max": {"type": "integer", "description": "Precio máximo en pesos chilenos (CLP): el presupuesto."},
    "genero": {"type": "array", "items": {"type": "string", "enum": GENDERS},
               "description": "male = hombre, female = mujer, unisex. Varias = cualquiera de ellas."},
    "concentracion": {"type": "array", "items": {"type": "string", "enum": CONCENTRATIONS},
                      "description": "edp = Eau de Parfum, edt = Eau de Toilette, parfum = extrait/perfume, "
                                     "cologne = colonia, eau_fraiche. Varias = cualquiera."},
    "volumen_min": {"type": "integer", "description": "Volumen mínimo en ml."},
    "volumen_max": {"type": "integer", "description": "Volumen máximo en ml."},
    "tienda": {"type": "array", "items": {"type": "string", "enum": list(STORE_NAMES)},
               "description": "Solo productos a la venta en alguna de estas tiendas."},
}
FILTER_PARAMS = {"precio_min": "min_price", "precio_max": "max_price", "genero": "gender",
                 "concentracion": "concentration", "volumen_min": "min_volume", "volumen_max": "max_volume",
                 "tienda": "store"}
LIMIT = {"type": "integer", "description": f"Cuántos resultados (1 a {MAX_RESULTS}, por defecto 8)."}


def _filters(args: dict) -> dict:
    return {param: args[name] for name, param in FILTER_PARAMS.items() if args.get(name) not in (None, [], "")}


def _limit(args: dict, default: int = 8) -> int:
    try:
        return max(1, min(MAX_RESULTS, int(args.get("limite") or default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], dict]


class Catalog:
    """Cliente de la API de BeautyMatch que expone las herramientas del modelo."""

    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 30.0) -> None:
        self._client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout,
                                              follow_redirects=True)  # los productos fusionados responden 308

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict | None = None) -> dict:
        """GET a la API. Los errores se devuelven como {"error": ...}."""
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as error:
            return {"error": f"el catálogo no responde ({type(error).__name__})"}
        if response.status_code == 404:
            return {"error": "producto no encontrado"}
        if response.status_code == 410:
            return {"error": "producto retirado del catálogo"}
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text[:200]
            return {"error": f"el catálogo respondió {response.status_code}: {detail}"}
        return response.json()

    def healthy(self) -> bool:
        try:
            return self._client.get("/healthz", timeout=5).status_code == 200
        except httpx.HTTPError:
            return False

    def search_by_description(self, args: dict) -> dict:
        query = str(args.get("consulta") or "").strip()[:200]
        if not query:
            return {"error": "falta la consulta"}
        data = self._get("/search/semantic", {"q": query, "limit": _limit(args), **_filters(args)})
        if "error" in data:
            return data
        return {"resultados": [summary(item) for item in data["items"]]}

    def search_products(self, args: dict) -> dict:
        params: dict[str, Any] = {"limit": _limit(args), **_filters(args)}
        if args.get("texto"):
            params["q"] = str(args["texto"]).strip()[:200]
        if args.get("marca"):
            params["brand"] = str(args["marca"]).strip()
        if args.get("orden") in SORTS:
            params["sort"] = args["orden"]
        data = self._get("/products", params)
        if "error" in data:
            return data
        return {"total": data["total"], "resultados": [summary(item) for item in data["items"]]}

    def product_detail(self, args: dict) -> dict:
        product_id = str(args.get("product_id") or "").strip()
        if not product_id:
            return {"error": "falta product_id"}
        data = self._get(f"/products/{product_id}")
        if "error" in data:
            return data
        prices = sorted(data["prices"], key=lambda p: (not p["is_available"], p["price"]))
        cheapest = next((p for p in prices if p["is_available"]), None)
        return {
            "precio_mas_bajo": clp(cheapest["price"]) if cheapest else None,
            "tienda_mas_barata": store_name(cheapest["store"]) if cheapest else None,
            "product_id": data["product_id"],
            "nombre": data["canonical_name"],
            "marca": data["brand"],
            "concentracion": data.get("concentration"),
            "volumen_ml": data.get("volume_ml"),
            "presentacion": data.get("presentation"),
            "precios": [{
                "tienda": store_name(p["store"]),
                "precio": clp(p["price"]),
                "precio_normal": clp(p.get("list_price")),
                "disponible": p["is_available"],
                "precio_por_ml": clp(p.get("price_per_ml")),
                "url": p["listing_url"],
            } for p in prices],
        }

    def variants(self, args: dict) -> dict:
        product_id = str(args.get("product_id") or "").strip()
        if not product_id:
            return {"error": "falta product_id"}
        data = self._get(f"/products/{product_id}/variants")
        if "error" in data:
            return data
        return {"nombre": data["canonical_name"], "variantes": [summary(item) for item in data["items"]]}

    def offers(self, args: dict) -> dict:
        params: dict[str, Any] = {"limit": _limit(args)}
        if args.get("marca"):
            params["brand"] = str(args["marca"]).strip()
        if args.get("tienda"):
            params["store"] = args["tienda"]
        data = self._get("/offers", params)
        if "error" in data:
            return data
        items = [{
            "product_id": o["product_id"],
            "nombre": o["canonical_name"],
            "marca": o["brand"],
            "tienda": store_name(o["store"]),
            "precio": clp(o["price"]),
            "precio_normal": clp(o["list_price"]),
            "descuento_pct": o["discount_percent"],
            "url": o["listing_url"],
        } for o in data["items"]]
        result: dict[str, Any] = {"ofertas": items}
        if not items:
            result["nota"] = "No hay ofertas verificadas: hace falta más historial de precios o no hay descuentos."
        return result

    def tools(self) -> list[Tool]:
        """Herramientas que ve el modelo, con su descripción y parámetros."""
        return [
            Tool(
                "buscar_por_descripcion",
                "Busca perfumes del catálogo parecidos en significado a una descripción o a un nombre "
                "aproximado (con errores de ortografía, en otro idioma). OJO: solo compara con el NOMBRE y "
                "la MARCA de los productos, no conoce notas olfativas. Funciona mejor con nombres de "
                "perfumes, marcas o palabras que suelen ir en el nombre (vanilla, oud, sport, intense, "
                "aqua, rose, noir...). Devuelve productos a la venta con su precio más bajo.",
                {"type": "object", "properties": {
                    "consulta": {"type": "string", "description": "Qué buscar, hasta 200 caracteres."},
                    **FILTERS, "limite": LIMIT}, "required": ["consulta"]},
                self.search_by_description,
            ),
            Tool(
                "buscar_productos",
                "Busca en el catálogo por texto exacto en el nombre y/o por marca, con filtros y orden. "
                "Úsala para encontrar un perfume concreto por su nombre, ver qué hay de una marca, o listar "
                "lo más barato / con más descuento dentro de un presupuesto.",
                {"type": "object", "properties": {
                    "texto": {"type": "string", "description": "Palabras que deben estar en el nombre o la marca."},
                    "marca": {"type": "string", "description": "Marca exacta, p. ej. 'Lattafa', 'Carolina Herrera'."},
                    **FILTERS,
                    "orden": {"type": "string", "enum": SORTS,
                              "description": "relevance (con texto), name, price_asc, price_desc, discount, "
                                             "price_per_ml (más barato por ml)."},
                    "limite": LIMIT}},
                self.search_products,
            ),
            Tool(
                "ver_producto",
                "Precio actual de un producto en cada tienda, con el link de compra. Úsala antes de "
                "recomendar dónde comprar.",
                {"type": "object", "properties": {
                    "product_id": {"type": "string", "description": "El product_id de un resultado de búsqueda."}},
                 "required": ["product_id"]},
                self.product_detail,
            ),
            Tool(
                "ver_variantes",
                "Otros tamaños y presentaciones (sets, otras concentraciones) de la misma fragancia.",
                {"type": "object", "properties": {
                    "product_id": {"type": "string", "description": "El product_id de un resultado de búsqueda."}},
                 "required": ["product_id"]},
                self.variants,
            ),
            Tool(
                "ver_ofertas",
                "Descuentos verificados con el historial de precios (el precio 'normal' tachado es real), "
                "de mayor a menor ahorro.",
                {"type": "object", "properties": {
                    "marca": {"type": "string", "description": "Marca exacta."},
                    "tienda": FILTERS["tienda"], "limite": LIMIT}},
                self.offers,
            ),
        ]
