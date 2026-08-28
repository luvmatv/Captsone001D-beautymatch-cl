# BeautyMatch CL

Sistema de normalización e integración de catálogos de productos de belleza para comparación confiable de precios en tiendas chilenas.

Proyecto Capstone — Ingeniería en Informática, Duoc UC.

## Descripción

El mismo producto de belleza se publica con nombres, formatos y descripciones distintas en cada tienda online, lo que impide comparar precios de forma confiable entre perfumería, maquillaje y skincare. BeautyMatch CL integra catálogos de múltiples tiendas y los normaliza mediante un algoritmo de emparejamiento basado en embeddings y reglas de negocio.

Esta versión implementa y valida el modelo en la categoría de **perfumería**, por presentar atributos más estructurados (marca, concentración, volumen), dejando como trabajo futuro la extensión a maquillaje y skincare.

## Alcance

**Incluido en esta versión**
- Extracción automatizada de catálogos de al menos 6 tiendas chilenas de perfumería
- Normalización y emparejamiento de productos equivalentes entre tiendas
- Historial de precios y detección de descuentos ficticios
- Comparador web con ficha de producto consolidada

**Fuera de esta versión**
- Compra o checkout dentro de la plataforma
- Aplicación móvil nativa
- Verificación de autenticidad del producto
- Categorías de maquillaje y skincare (trabajo futuro)

## Arquitectura

- **Scraping:** Python + Playwright
- **Normalización:** embeddings + reglas de negocio (marca, ml, concentración)
- **Base de datos:** PostgreSQL + pgvector
- **API:** FastAPI
- **Frontend:** React

## Metodología

Desarrollo bajo Scrum, sprints de 2 semanas.

Ingeniería en Informática, Duoc UC
