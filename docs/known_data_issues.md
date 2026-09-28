# Problemas conocidos en los datos de las tiendas

Errores de origen detectados en los sitios, que el pipeline no corrige
automáticamente. Antes de tratar un dato raro como caso aislado, revisar si
calza con alguno de estos patrones.

## Preunic

### Volumen de la línea Natalie Botanicals: 250 ml en la ficha técnica (real: 205 ml)

- **Detectado:** 2026-09-26, al leer el volumen desde el campo `Formato:` de
  la ficha técnica.
- **Qué pasa:** la ficha de 3 de las 4 colonias Botanicals individuales dice
  `250ml`: Apple, Cherry y Raspberry. Cup Cake dice `205ml`.
- **Por qué creemos que es un error:** todas las demás fuentes de la misma
  línea dicen 205 ml:
  - los estuches Botanicals de Preunic (nombre, JSON-LD y ficha "205ml + 100ml");
  - "Botanicals Body Spray Sweet Gummies 205ml" (nombre, ficha y descripción);
  - las publicaciones de Maicao, "Colonia Spray Cherry/Raspberry 205 mL".
- **Causa probable:** dígitos transpuestos (205 → 250) o la plantilla de
  250 ml de los body mists de Natalie copiada a esta línea. Con los datos
  disponibles no se puede distinguir entre las dos.
- **Efecto en el matching:** la regla de volumen veta esos 3 pares contra
  Maicao. Se pierde el match, pero no se fusiona mal (dirección segura).
- **Qué hacer si reaparece:** si un volumen de la ficha técnica contradice al
  resto de la línea, desconfiar de la ficha antes que de los nombres.

### Alcance de la categoría "Perfumes y Fragancias" (no hay tope de 500)

- **Revisado:** 2026-09-27, porque todos los scrapes traían exactamente 500 productos.
- **Qué muestra el sitio:** la categoría dice "N productos" y el botón "Cargar
  más productos" pide páginas de 24 a la API de búsqueda del sitio (Empathy),
  que informa el total (`numFound`). El 27/09 el total era **497**. Los 497
  estaban en el scrape del 25/09, que traía 500; los 3 restantes (body mists
  "B Fresh" de 221 ml) salieron de la categoría. 500 era el total de ese día,
  no un tope.
- **Sin tope en 500:** en una categoría más grande (maquillaje, 3006
  productos) la API devuelve productos desde la posición 500 y desde la 1000.
  Sí tiene un límite de paginación en la posición 2496, muy por encima de
  perfumes.
- **Lo que el listado no incluye, a propósito:**
  - 14 productos marcados `storeExclusive` (sets y perfumes que se venden solo
    en algunas tiendas físicas). No se pueden comprar online.
  - El listado se filtra por la ubicación elegida (Santiago). Hoy no cambia
    el total de perfumes.
  - 3 body mists "Juicy Bomb" están en otra categoría, `perfume`, fuera de
    "Perfumes y Fragancias", así que el scraper no los ve.
- **Qué vigilar:** si el total del sitio supera ~2400, el scraper (100 clics
  de "cargar más", 2424 productos) y la API se quedarían cortos. En ese caso
  el total de la página ya no coincidiría con lo leído y la carga no
  desactivaría nada (ver `site_total` en [daily_run.md](daily_run.md)).

### Nombre con un espacio dentro del volumen: "20 5Ml"

- **Detectado:** 2026-09-26.
- **Qué pasa:** "Estuche Natalie Botanicals Raspberry 20 5Ml + Cup Cake 100 Ml
  Edt": el extractor lee **5 ml** (el JSON-LD dice "205Ml").
- **Efecto:** el volumen guardado para ese estuche es incorrecto. Como es un
  set, la regla de presentación lo separa de las botellas sueltas, así que por
  ahora no produce fusiones erróneas.

## Maicao

### Nombres truncados con abreviaturas

"ARIANA GR.MOD VAI.SP236ML", "Yara W.EDP SP100M", etc. Se expanden en
`src/matching/normalization.py` antes de generar embeddings y antes de buscar
el volumen en el nombre.

## Bugs pendientes del pipeline de matching

### Productos Armaf asignados a la marca Lattafa

- **Detectado:** 2026-09-26, en la respuesta de `GET /products?brand=lattafa`.
- **Ejemplos:** "Lattafa Armaf Club Deso.SP 200 ml" y "Lattafa Armaf
  Mand.Deso.Bod.200ML 200 ml" aparecen como productos Lattafa. Armaf es otra
  casa, y Preunic la trae con su propia marca ("Armaf Odyssey Mandarin Hombre
  Edp 100 ml", marca `Armaf`).
- **Origen del dato:** las publicaciones de Maicao "Armaf Club Deso.SP200ML" y
  "Armaf Mand.Deso.Bod.200ML" vienen con `raw_brand = 'LATTAFA'`. Seguramente
  Maicao las cargó bajo el distribuidor de las dos marcas.
- **Por qué es un bug del pipeline:** el pipeline toma `raw_brand` tal cual.
  No se da cuenta de que el nombre empieza con otra marca que ya existe en el
  catálogo (Armaf, por las publicaciones de Preunic). Con eso:
  - la fragancia canónica queda con marca Lattafa y nombre "Armaf ...";
  - esas publicaciones solo se comparan con productos Lattafa, porque los
    candidatos se buscan dentro de la misma marca. Si Preunic vende el mismo
    producto como Armaf, el match se pierde. Es la dirección segura: no
    produce fusiones erróneas.
- **Arreglo posible (pendiente):** antes de buscar candidatos, si el nombre
  empieza con una marca conocida distinta de `raw_brand`, usar esa marca.
  Hay que calibrarlo con datos. Hay nombres que contienen otra marca sin ser
  de ella ("Lattafa Yara Tous" es de Lattafa, no de Tous), así que solo debe
  aplicarse cuando la otra marca es la que abre el nombre.

## Limitaciones del modelo de datos

### `fragrances.gender = 'unisex'` no distingue "unisex" de "no informado"

- **Qué pasa:** el género se deduce de las palabras del nombre ("Hombre",
  "Mujer", "Women"...). El pipeline (`build_plan` en
  `src/matching/pipeline.py`) asigna a la fragancia el primer género que
  encuentra en sus publicaciones y, si ninguna lo indica, guarda `'unisex'`
  por defecto.
- **Efecto:** en `fragrances.gender`, `'unisex'` puede significar que la
  fragancia es realmente unisex o que ningún nombre informó el género. Hoy no
  se pueden distinguir, así que cualquier filtro o estadística por género
  cuenta como unisex las fragancias sin dato.
- **No afecta el matching:** las reglas trabajan con el género deducido
  (`None` si no se sabe), no con esta columna. El valor por defecto solo se
  aplica al escribir la fragancia canónica.
- **Arreglo posible (pendiente):** permitir `NULL` (o un valor `'unknown'`) en
  la columna y dejar `'unisex'` solo cuando alguna fuente lo diga.
