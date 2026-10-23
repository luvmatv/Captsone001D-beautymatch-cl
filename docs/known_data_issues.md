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
  - El listado se filtra por la ubicación elegida (Santiago). El 27/09 no
    cambiaba el total de perfumes; el 03/10 dejaba fuera 10 estuches activos
    (ver "Preunic no marca agotados" más abajo).
  - 3 body mists "Juicy Bomb" están en otra categoría, `perfume`, fuera de
    "Perfumes y Fragancias", así que el scraper no los ve.
- **Qué vigilar:** si el total del sitio supera ~2400, el scraper (100 clics
  de "cargar más", 2424 productos) y la API se quedarían cortos. En ese caso
  el total de la página ya no coincidiría con lo leído y la carga no
  desactivaría nada (ver `site_total` en [daily_run.md](daily_run.md)).

### Preunic no marca agotados: los saca del listado

- **Revisado:** 2026-10-03.
- **Qué pasa:** ni la tarjeta del listado ni la ficha dicen "agotado". La
  tarjeta no trae ningún dato de stock (el scraper buscaba selectores que
  nunca coincidieron: `availability` venía vacío en las 470). La ficha dice
  "Disponible" y "Disponible en Santiago" incluso en productos que ya no se
  venden; solo se desactiva el botón "Agregar a la bolsa". El dato real está
  en la API de búsqueda (Empathy): cada producto tiene `state` (`active` /
  `not_active`) y las comunas y zonas donde se puede comprar. La categoría
  pide solo los `active` que se venden en la ubicación por defecto.
- **Cómo lo tratamos:** el scraper marca cada tarjeta como `available` (la
  categoría solo muestra productos comprables). Un producto que se agota sale
  del listado y el loader lo desactiva (`is_active = false`): conserva su
  producto y su historial de precios, pero la API deja de mostrar esa oferta.
  No se registra como "sin stock" (`is_available = false`), a diferencia de
  Maicao, Salcobrand y Beauty Perfumes, que siguen publicando sus agotados.
- **Depende del total de la página:** solo se desactiva lo que falta si las
  publicaciones leídas cuadran con el "N productos" de la categoría
  (`site_total`). Si no cuadran, la carga guarda los precios pero no
  desactiva nada, y un producto agotado seguiría activo hasta el próximo
  scrape completo.
- **Comprobado el 03/10:** las 33 publicaciones de Preunic inactivas en la base
  aparecen en Empathy como `not_active`, con la misma URL y sin comunas;
  ninguna de las 470 activas figura como `not_active`. En la categoría hay 253
  productos `not_active` (220 nunca estuvieron en nuestra base).
- **Límites:**
  - La ubicación por defecto condiciona qué productos se ven: 10 estuches
    `active` se venden solo en 1 a 6 comunas, quedan fuera del listado y
    nunca se cargan (480 activos en Empathy, 470 en la página). Si Preunic
    cambia la ubicación por defecto, cambia el catálogo que vemos.
  - `not_active` no distingue un agotado temporal de un producto
    descontinuado: los dos salen del listado igual.

### Nombre con un espacio dentro del volumen: "20 5Ml"

- **Detectado:** 2026-09-26.
- **Qué pasa:** "Estuche Natalie Botanicals Raspberry 20 5Ml + Cup Cake 100 Ml
  Edt": el extractor lee **5 ml** (el JSON-LD dice "205Ml").
- **Efecto:** el volumen guardado para ese estuche es incorrecto. Como es un
  set, la regla de presentación lo separa de las botellas sueltas, así que por
  ahora no produce fusiones erróneas.

### Orden con empates: tarjetas repetidas y faltantes en el corte entre tandas

- **Qué pasa:** el orden de la categoría tiene empates: dos publicaciones
  vecinas pueden cambiar de lugar entre una consulta y otra. "Cargar más" pide
  cada tanda de 24 por separado; si un par empatado cae justo en el corte entre
  dos tandas, una sale **dos veces** y la otra **ninguna**. El total de
  tarjetas cuadra con el de la página, pero las publicaciones distintas no.
- **Visto:** 25/09 (dos scrapes, corte 71|72), 08/10 (corrida 38, corte
  47|48: Eminence Latitud Patagonia repetida, Etienne Carmín faltante) y 12/10
  (corrida 43, **cuatro** empates en 311|312, 407|408 y 455|456, todos
  estuches o sets). En las tres ocasiones la tienda quedó `partial` sin
  desactivar nada (la regla exacta lo detectó), pero esas publicaciones se
  quedaron sin precio del día.
- **Arreglo** (`src/scrapers/stores/preunic/listing.py`):
  1. si las publicaciones distintas igualan el total, se usa la lectura tal
     cual (lo normal: sin costo extra);
  2. si no, el scraper lee el listado **una segunda vez** (la misma carga y
     los mismos clics, unos 70 s más). Si esa segunda lectura sola cuadra, se
     usa solo ella;
  3. si tampoco, se unen las dos. La unión cuenta como completa solo si (i) la
     página informó el mismo total en ambas, (ii) la unión tiene exactamente
     ese total, y (iii) cada publicación vista en una sola lectura está, en
     esa lectura, a una posición o menos de un corte entre tandas (donde caen
     los empates; una publicación que entró o salió del catálogo puede estar
     en cualquier parte);
  4. una unión rechazada carga los precios de todo lo visto, pero queda
     `listing_complete: false`: el loader no desactiva nada aunque los números
     cuadren.
- **En el JSON** (`pagination`): `cards_read`, `urls_distinct`,
  `urls_repeated` (con posiciones), `batch_ends`, `passes` (cada lectura),
  `listing_source` (`first_pass`, `second_pass`, `union`), `recovered`,
  `listing_complete` y `union_rejected` (qué condición falló y por qué). Si la
  segunda lectura falla, `second_pass_error` y queda la primera, incompleta.
- **Medido** con los scrapes guardados hasta el 08/10: la unión habría
  completado 21 de 21 scrapes; un reintento solo, 20 de 21 (el 25/09 dos
  lecturas seguidas fallaron en el mismo empate). Esa medición usó como
  segunda lectura scrapes de minutos a días después.
- **Prueba real** (12/10 11:14, scraper de la rama): la primera lectura tuvo
  un empate (Agatha Ruiz de la Prada Beso repetida en 455|456) y la segunda,
  un minuto después, **el mismo**: la unión quedó en 478 de 479 y se rechazó
  (`union_matches_total`). El resultado es el de antes (`partial`, nada
  desactivado), con unos 35 s más. **Límite conocido:** un empate que dura
  minutos no se recupera con una segunda lectura inmediata.

### Catálogo dividido en dos categorías (14/10)

- **Qué pasó:** el 14/10 `/t/perfumes-y-fragancias` pasó de 479 a **77**
  productos (40 mujer, 34 hombre, 3 sueltos) y la tienda creó
  `/t/perfume` con **405**. La corrida 45 leyó solo los 77: la página misma
  declaraba 77, así que la lectura "cuadraba". El límite del 25 % evitó
  desactivar las otras 402 (84 %), pero esas 402 quedaron sin precio ese día.
- **Comprobado** con una lectura de prueba de `/t/perfume` (14/10): las 402
  que faltaron están todas ahí, ninguna publicación está en las dos
  categorías, hay 3 nuevas (`body-misy-juicy-bomb-02/03/04`) y la URL de cada
  publicación es la misma de siempre (`/products/<slug>`, no depende de la
  categoría), así que su producto y su historial se mantienen.
- **Arreglo:**
  - Las categorías que se leen están en **`config/scraping.json`**
    (`preunic.category_urls`), no en el código. Para cambiarlas: editar el
    archivo, commit y `git pull` en la copia de producción. El CLI acepta
    `--category-url` (repetible) para una prueba puntual.
  - Cada categoría se compara con **su propio** total (con la segunda lectura
    por empates de arriba). La tienda está completa solo si **todas** lo
    están. Si una falla o no cuadra, se cargan los precios de lo leído, la
    tienda queda `partial` y no se desactiva nada.
  - Las publicaciones se unen por URL: una que esté en dos categorías cuenta
    una vez (`in_several_categories` en el JSON; si su precio difiere entre
    categorías se usa el de la primera y se cuenta en
    `price_differs_between_categories`).
  - El límite del 25 % sigue a nivel tienda, sobre las publicaciones activas
    que no están en la unión de todas las categorías.
- **Alertas** (`src/loader/preunic_alerts.py`): dejan la tienda `partial`,
  **no desactivan nada** y **sí cargan los precios**:
  1. **Caída del total**: las publicaciones distintas de la tienda bajan más
     de un 10 % respecto del último listado completo. El total de una
     categoría alerta solo si **la tienda también cae**: si una categoría baja
     y la tienda se mantiene, es una reorganización (sus publicaciones se
     movieron a otra categoría), su nuevo total pasa a ser el punto de partida
     y queda anotado ("total 479 -> 77 while the store's total holds (479 ->
     482): a reorganization, new baseline"). Una categoría nueva, sin
     historial, nunca alerta. Si el mismo total más bajo se repite **3
     corridas seguidas**, se acepta como nuevo punto de partida y queda
     anotado ("total 85 accepted as the new baseline after 3 runs in a row at
     it (was 100)"). Cubre el hueco del 25 %: una caída del 21 % (380 de 479)
     habría desactivado 99.
  2. **Exceso de publicaciones nuevas**: más del 10 % de las leídas no existen
     en la tienda (por ejemplo, si cambiara el formato de las URL).
  - El historial son los JSON anteriores de Preunic en la misma carpeta (la
    copia de producción los guarda todos); se recalcula cada vez, sin guardar
    estado aparte.
- **Al desplegarlo:** la primera corrida con el scraper nuevo lee 77 + 405
  = 482 publicaciones (3 nuevas). La tienda pasa de 479 a 482, así que la
  baja de `/t/perfumes-y-fragancias` (479 → 77) se toma como reorganización:
  Preunic queda completo, sin alertas y sin desactivar nada. Comprobado
  cargando la lectura real del 14/10 con el historial de producción en una
  copia de la base.

## Maicao

### El total de la API (307) no coincidía con lo que leía el scraper (305) — resuelto

- **Detectado:** 2026-09-29, corridas 25 a 28: "read 305 listings, the store
  reports 307". Maicao quedaba `partial` y no desactivaba publicaciones.
- **Causa confirmada (2026-09-30):** se compararon los 307 `productId` de las
  26 respuestas de `product-search` de un scrape con los 305 IDs que guardaba
  el scraper. Faltaban 2, los dos en la última página:
  - `580587` "Perfume EDP Gold Elixir 100ml" →
    `/perfume-edp-gold-elixir-100ml/580587.html`
  - `580588` "Perfume EDP Absolutely blue 100ml" →
    `/perfume-edp-absolutely-blue-100ml/580588.html`

  Sus URLs usan un **ID numérico**, no el formato `CLMC_…` del resto, y el
  scraper solo reconocía enlaces con `/CLMC_`. Además, **la API los lista sin
  precio** (`price: null`): están publicados pero no a la venta.
  No era un problema de paginación: el scraper recorría las mismas 26 páginas
  que la API.
- **Arreglo:**
  - el scraper reconoce los enlaces `/<slug>/CLMC_<n>.html` y
    `/<slug>/<número>.html`, y el SKU se lee en los dos formatos;
  - el corte de la última página cuenta **productos**, no enlaces (cada
    producto tiene dos), para que una última página de 7 productos (14
    enlaces) siga terminando en `short_page`;
  - una publicación **sin precio** se guarda en `raw_listings` con
    `is_active = false`, sin fila en `price_history`. Así no se empareja ni se
    muestra, pero cuando aparezca con precio se reactiva con su mismo ID, en
    vez de ser una publicación nueva;
  - el total que se compara (`site_total`) cuenta solo los productos **con
    precio**: el scraper guarda el total de la API (`site_total_reported`, 307),
    los sin precio (`unpriced_in_api`) y `site_total` = 307 − 2 = 305, que se
    compara con las publicaciones leídas con precio.
- **Verificado** con un scrape real: 307 leídos, 2 sin precio, `site_total`
  305 = 305 con precio, `short_page` → Maicao queda completo.

### Incidente: 8 precios no leídos dejaron publicaciones inactivas (08/10)

- **Qué pasó:** en la corrida 39 (08/10 16:23) llegaron 12 tarjetas sin
  precio en vez de 4. Las 8 de más (colonias Babyland y Simonds, Flor de Mayo
  Seashell, Beauty 100 Stars) tenían precio en la corrida de las 09:00, y la
  API de búsqueda de la tienda no las listaba sin precio: el scraper no leyó un
  precio que existía. El loader las dejó `is_active = false`, sin contarlas
  como desactivadas, y salieron de la API y del matching (`new_product` bajó de
  2322 a 2314).
- **Arreglo, solo Maicao** (`PRICE_NOT_READ` en `src/loader/raw_listings.py`).
  Una tarjeta sin precio:
  - si la tienda la informa sin precio (`unpriced_in_api`): inactiva, como
    antes;
  - si nunca tuvo precio: inactiva, como antes;
  - si tiene historial de precios y la tienda no la informa sin precio: es un
    **precio no leído**. Queda como estaba (activa o no), sin fila de precio;
    solo se actualiza `last_seen_at`, y el scrape queda `partial` con la nota
    "N listings with a price history came without a price the store did not
    report: price not read, kept as they were";
  - si lleva 3 scrapes seguidos sin precio leído, se desactiva. Se cuentan los
    scrapes de la tienda que dejaron precios después de su último precio, más
    el actual.
- **Defensa, en todas las tiendas:** las desactivaciones por falta de precio
  se cuentan en `listings_deactivated` y pasan por el mismo límite del 25 %
  que las publicaciones que faltan. En Preunic, Salcobrand y Beauty Perfumes
  una tarjeta sin precio sigue quedando inactiva (no hay "precio no leído"),
  pero si fueran a quedar inactivas más del 25 % de las activas, no se
  desactiva ninguna. Si el sitio cambiara su marcado y ninguna tarjeta
  trajera precio, no se desactiva nada: todas son precios no leídos y, sin
  precios cargados, la tienda queda `failed`. Si la API dijera que ninguna
  tiene precio, el límite tampoco deja desactivar nada.

### Catálogo múltiplo de 12: la última página no es corta (15/10)

- **Qué pasó:** la corrida 46 (15/10 16:11) leyó **336** productos, exactamente
  28 páginas de 12. Como la página 28 vino llena, el scraper pidió la 29 y
  vino vacía (`stop_reason: empty_page`). La API declaraba 336
  (`site_total_reported`) y lo leído con precio (328) igualaba `site_total`,
  pero el loader solo aceptaba `short_page` como fin limpio: Maicao quedó
  `partial` y no desactivó nada.
- **Arreglo** (`_maicao_stop` en `src/loader/raw_listings.py`): `empty_page`
  es fin limpio **solo si** todas las páginas leídas vinieron llenas
  (`final_products == pages_fetched × page_size`) y lo leído es exactamente el
  total que declara la API (`final_products == site_total_reported`). Una
  página vacía a mitad del catálogo, un total distinto o un archivo sin esos
  datos (anteriores al 16/10) siguen siendo `partial`. Con un catálogo que no
  es múltiplo de 12, `short_page` como siempre.

### La primera página vino sin productos (18/10, causa sin determinar)

- **Qué pasó:** en la corrida 49 (18/10 20:54, minutos después de que el PC
  despertara) la primera página del listado no tenía ningún enlace de
  producto. La API de búsqueda que la página consulta sí respondió (339
  productos), así que la página cargó al menos en parte. El scraper terminó
  con `empty_page` en 7 s y el loader rechazó el archivo vacío: no se cargó ni
  se desactivó nada. En la corrida siguiente (50, 23:13) leyó los 339 con
  normalidad.
- **Por qué no se sabe la causa:** no quedó la URL final, el título, el
  estado HTTP, el HTML ni una captura. No se puede distinguir entre una página
  que tardó más de 3 s en dibujar los productos, un cambio de HTML o una
  página distinta (un aviso, una verificación).
- **Registro agregado:** cuando una página del listado viene sin enlaces de
  producto, el scraper guarda junto al JSON
  `maicao_<fecha>_empty_offset<N>.html` y `.png`. Además anota en el log y en
  `pagination.empty_page`:
  - la URL final, el título y el estado HTTP;
  - cuántos enlaces tiene la página y cuántas respuestas de la API de búsqueda
    llegaron;
  - el comienzo del texto visible.

  El comportamiento no cambia: sigue terminando en `empty_page`. Si vuelve a
  pasar, mirar esos archivos antes de cambiar nada.

### Nombres truncados con abreviaturas

"ARIANA GR.MOD VAI.SP236ML", "Yara W.EDP SP100M", etc. Se expanden en
`src/matching/normalization.py` antes de generar embeddings y antes de buscar
el volumen en el nombre.

## Salcobrand

### Incidente: el listado abrió filtrado por "Ofertas Cyber" (03 y 04/10)

- **Qué pasó:** las corridas diarias del 03/10 (21:03) y del 04/10 (09:10)
  fallaron en Salcobrand con "the category page did not load its Algolia
  listing" (`exit_code_1`); no se cargó nada de esa tienda esos días. El
  último scrape bueno es del 02/10.
- **Causa encontrada (diagnóstico del 04/10, una carga de la página, sin
  scrapear):** durante el evento Cyber, la categoría abre con el filtro
  "OFERTAS CYBER: Si" aplicado por defecto. La consulta del listado a Algolia
  pasó de `[["product_categories.lvl1:Belleza > Perfumes & Fragancias"]]` a
  `[["cyber:Si"],["product_categories.lvl1:..."]]`: 183 de los 419 perfumes.
  Por qué las corridas no vieron ninguna consulta reconocible no quedó
  registrado (el scraper no guardaba lo que veía).
- **El riesgo:** con el listado filtrado, un scrape habría leído 183 productos,
  el total de esa consulta (`nbHits` 183) habría cuadrado con lo leído y el
  loader habría desactivado las otras ~236 publicaciones.
- **Defensas agregadas el 04/10:**
  - El scraper solo acepta la consulta del listado si su único filtro es la
    categoría (más la ventana de disponibilidad que el sitio agrega siempre).
    Con cualquier otro filtro se detiene con un error claro
    (`UnexpectedListingFilter`).
  - Para todas las tiendas: si una carga completa fuera a desactivar más del
    25 % de las publicaciones activas de la tienda (umbral configurable,
    `--max-deactivation-share`), no desactiva nada y la tienda queda
    "partial" con una nota.
- **Probado el 05/10 (de día, solo lectura):** el filtro es una casilla del
  panel "OFERTAS CYBER" que la página marca en "Si" al cargar; la URL no
  cambia nunca. Desmarcándola, la consulta vuelve a ser solo por categoría
  (419 productos, 18 páginas) y la paginación la mantiene. Estable en tres
  cargas (04 y 05/10).
- **Corrección (05/10):** si la guarda rechaza el primer listado y el panel
  "OFERTAS CYBER" existe con algo marcado, el scraper lo desmarca con el
  control de la página y vuelve a leer, otra vez a través de la guarda. No
  toca ningún otro filtro: cualquier otro sigue deteniendo el scrape, y sin
  el panel se lee como abre. El JSON del scrape anota lo desmarcado
  (`pagination.unchecked_sale_filter`). Scrape real de prueba, sin cargar:
  419 productos en 18 páginas, completo, 0 publicaciones por desactivar.

### Los sets no tienen una fuente confiable de volumen (limitación conocida)

- **Revisado:** 2026-09-30, al buscar el volumen de las publicaciones que no
  lo traen en el nombre.
- **Qué hay en el sitio:**
  - la ficha del producto dice `Formato: 1 Unidad` o `Formato: Set`, y el
    campo `Cantidad` aparece vacío. No hay un equivalente al `Contenido:` de
    Maicao ni al `Formato:` de Preunic;
  - la única otra pista es el precio por 100 ml que muestra el sitio. Al
    deducir volumen = precio / (precio por 100 ml) × 100 y compararlo con las
    publicaciones cuyo volumen sí se conoce, coincidió en 266 de 276
    (**3,6 % de error**).
- **Decisión:** no se deduce el volumen. Un 3,6 % de volúmenes equivocados es
  demasiado para la prioridad del proyecto (una fusión errónea es peor que un
  match perdido). Las publicaciones de Salcobrand sin volumen en el nombre,
  sobre todo los sets, quedan sin volumen.
- **Efecto:** sin volumen la regla de volumen no puede confirmar el par, así
  que esas publicaciones se emparejan menos (dirección segura). No es una
  tarea pendiente: solo cambia si Salcobrand empieza a publicar el contenido
  en la ficha.

## Beauty Perfumes

### Marcas que no son del producto (limitación conocida, sin arreglo)

- **Revisado:** 2026-10-16, sobre los nombres que empiezan con otra marca del
  catálogo.
- **Qué pasa:** la tienda pone en el campo de marca algo que no es la marca del
  perfume:
  - su propio nombre, «Beauty Perfumes», en *Ariana Grande Sweet Like Candy*
    (set), *Paris Corner Mango Flames*, *YSL Black Opium Over Red* y *Mykonos
    Dreamscape / Glitch*;
  - «Lattafa» en *Armaf Club de Nuit Woman / Bling*, *Rave Nuit Parfaite / Au
    Soleil* y *Ard Al Zaafaran Badee Al Oud*;
  - otra casa del mismo grupo: *Ard Al Zaafaran* con «Al Haramain» o
    «Fragrance World», y *Fragrance World IS* con «Maison Alhambra».
- **Efecto:** el pipeline toma la marca tal cual. Esas publicaciones se comparan
  con productos de otra marca, así que lo más probable es que pierdan su pareja
  en otras tiendas: es la dirección segura, sin uniones erróneas. Además el
  producto se muestra con la marca equivocada. No está medido cuántas parejas
  se pierden.
- **No son errores:** *Halloween* (línea de Jesús del Pozo), «VICTORIA´S
  SECRET» con tilde invertida, *Essence* (Etienne), *Diavolo* (Banderas),
  *Colonia Inglesa* (Cell Skin) y *Quimera* (JLP).
- **Arreglo posible (pendiente):** el mismo que para Armaf en Maicao (ver
  [Productos Armaf asignados a la marca Lattafa](#productos-armaf-asignados-a-la-marca-lattafa)):
  usar la marca con la que abre el nombre cuando es otra marca conocida.

### Testers marcados de varias formas; no se cargan

- **Revisado:** 2026-10-02, sobre las 2379 fichas de `products.json`.
- **Qué pasa:** cada producto tiene una sola variante, así que el tester es
  un producto aparte, pero ningún campo lo marca siempre. De 371 testers: 362
  lo dicen en el título, 3 solo en el tipo (`product_type = Tester`), 2 solo
  en el handle (`...-tester-original`), 2 solo en la descripción ("IMPORTANTE:
  Tester sin tapa y sin celofán") y 2 solo con el sufijo "(T)" del título (el
  mismo D&G Capri In Love se vende a $59.900 y como "(T)" a $50.000, con
  "Perfume TESTER" en la descripción).
- **Qué hace el scraper:** descarta los testers con cualquiera de esas marcas,
  y también decants (ninguno al 2026-10-02), desodorantes, cremas, aromas
  ambientales y frascos "sin celofán". Se descartan antes de escribir el JSON:
  ningún paso posterior los ve. El resultado del scrape cuenta los descartes
  por motivo (`pagination.excluded`).
- **Sin total de la tienda:** Shopify no publica el tamaño del catálogo. La
  carga cuenta como completa si el scraper llegó a la página vacía de
  `products.json` y trae al menos el 80 % de las publicaciones activas.

### Género "(M)/(H)/(U)" en los nombres: solo manda a revisión

- **Detectado:** 2026-10-02, al etiquetar `automatch_beautyperfumes_v1.csv`.
  El pipeline aceptó solo "ANTONIO BANDERAS THE ICON 100ML EDP (M)" (la
  versión de mujer, 2023, frasco rosado) con el The Icon de hombre de Preunic
  ("Antonio Banderas The Icon EDP 100 Ml", categoría "Perfumes Hombre").
  Etiquetado "different": cuando la tienda entre al matching, la etiqueta
  veta ese par.
- **Los marcadores son confiables:** "(M)" mujer y "(H)" hombre coinciden con
  las palabras de género del nombre en 288 de 289 casos. "(U)" no: también
  marca líneas de hombre ("RASASI HAWAS LONDON MEN EDP (U)").
- **Por qué no se leen como palabras de género:** leer "(M)/(H)" como género
  evita esa fusión, pero rompe 4 pares correctos etiquetados y pierde un
  quinto, todos de líneas que se venden en las dos versiones (The Icon, The
  Icon Elixir, Beso). El otro lado del par no indica género, ni en el nombre
  ni en una categoría que el pipeline lea (Preunic lo dice solo en su
  categoría), y la regla de líneas con dos versiones veta cuando solo un
  nombre trae género. Medido sobre una copia con las cuatro tiendas.
- **Regla aplicada (`marker_gender_conflict` en `src/matching/rules.py`):**
  cuando el género de un lado viene solo del código de la tienda, el par va a
  revisión (`review:gender_marker`) si el otro lado dice el género contrario,
  o si no dice ninguno y la línea se vende en dos versiones. El código nunca
  veta ni acepta por sí mismo, y un veto de las demás reglas se mantiene.
- **Medido sobre la copia con las cuatro tiendas (20 934 pares):** cambian 7
  decisiones. The Icon EDP (M) contra Preunic pasa de aceptado a revisión, y
  su etiqueta "different" lo veta. The Icon EDP (H), The Icon Elixir, The Icon
  EDT 200 ml y Beso pasan de aceptados a revisión, donde sus etiquetas "same"
  los resuelven (The Icon Elixir se sigue aceptando por cadena). Dos pares
  Tommy Now / Tommy Girl Now sin etiqueta ya estaban en revisión. Ningún par
  etiquetado cambia de dirección. Precisión de los aceptados: 503/504 →
  500/500.
- **Falta:** agregar Beauty Perfumes a `MATCHING_STORES` es un paso aparte.

### Un mismo producto publicado dos veces: Paris Hilton Gold Rush Man

- **Revisado:** 2026-10-05, con fotos.
- **Qué pasa:** Beauty Perfumes publica el mismo perfume dos veces, con SKU
  distinto:
  - "PARIS HILTON GOLD RUSH 100ML EDT (H)", SKU `GOLDRUSH100H`
    (`/products/paris-hilton-gold-rush-edt-100ml-hombre-goldrush100h`):
    agotado, a $25.000.
  - "PARIS HILTON GOLD RUSH MAN 100ML EDT (H)", SKU `PHGOLDRUSH100H`
    (`/products/gold-rush-man-paris-hilton-100ml-phgoldrush100h`): con stock,
    a $29.900.
  Las fotos son idénticas y la caja dice MAN en las dos; ambas son EDT 100 ml
  (H). Precios y stock según la lectura del 05/10.
- **Cómo lo tratamos:** quedan unidas en un solo producto ("Paris Hilton Gold
  Rush EDT 100 ml"), que es lo correcto: "Man" cuenta como palabra de
  público, igual que "Hombre", y no separa productos dentro de una tienda.
  Es el caso de una tienda repitiendo un producto, no una fusión errónea.
- **Efecto visible:** la API muestra una oferta por publicación, así que la
  ficha del producto lista dos ofertas de Beauty Perfumes. El precio más bajo
  del listado considera solo las disponibles ($29.900 mientras la otra siga
  agotada).

## dperfumes

### Volumen distinto en el nombre y en el atributo "Formato"

- **Detectado:** 2026-10-04, al evaluar la tienda.
- **Qué pasa:** en 12 de 1.622 productos el nombre y el atributo Formato dan
  tamaños distintos. Ejemplos: "Angel Nova Eau de Parfum Fruitée 25 ml"
  con Formato 125 ml (y una imagen de 100 ml); "Kenzo Homme Sport Extreme
  Eau de Toilette 50 ml" con Formato 100 ml.
- **Cómo lo tratamos:** volumen desconocido. El scraper deja `volume` vacío y
  anota la discrepancia en `volume_note`; el loader no vuelve a leer el
  volumen del nombre en ese caso. Sin volumen, la publicación queda
  pendiente en el matching en vez de arriesgar un emparejamiento con el
  tamaño equivocado.

### Qué se excluye en el scraper

- Se leen solo las categorías de perfumería: `perfumes`, `perfumes-nicho`,
  `sets-de-regalo` y `brumas` (1.622 productos el 04/10). Los decants tienen
  su categoría pero no aparecen en la API.
- Se excluyen: testers (2), recargas "Recarga" (10, el repuesto), desodorantes
  sueltos (17), sets con loción corporal (2) y jabones sueltos (3, de Hermès).
  Scrape real del 04/10: 1.622 vistos = total de la API, 1.588 cargables,
  163 páginas en 6 minutos.
- Se mantienen: los sets de regalo y de miniaturas, los sets que incluyen un
  desodorante (como en las otras tiendas) y los frascos "Recargable" (15),
  que son el producto completo.
- **A vigilar:** "Vaporizador Globe Trotter Zinc Edition" de Maison Francis
  Kurkdjian (11 ml según Formato) puede ser un estuche de viaje recargable,
  como el "Perfumero" de los sets de Etienne. Se carga; revisar si aparece
  en un par.

### El género viene en un atributo, no en el nombre

- **Calibrado:** 2026-10-21, con un scrape real (1.571 productos cargables).
- **Qué declara:** el atributo "Género" trae "Masculino" (654), "Femenino"
  (590) o los tres términos a la vez, "Femenino, Masculino, Unisex" (321,
  los perfumes para todo público). 6 no lo traen.
- **Qué tan confiable es:** donde el propio nombre dice el género, coincide en
  283 de 283. Donde solo lo dicen los nombres de nuestras otras tiendas para
  la misma línea, coincide en 254 de 255; el otro, "Animale", es la versión
  de mujer que en nuestro catálogo solo estaba de hombre.
- **Cómo se mapea** (`to_declared_gender`, columna
  `raw_listings.declared_gender`, migración 008): Masculino → `male`,
  Femenino → `female`, varios términos → `unisex`, sin atributo o con un
  término desconocido → `NULL`.
- **Cómo lo usa el matching:** igual que los códigos "(M)"/"(H)" de Beauty
  Perfumes (`with_declared_gender` lo escribe como ese código). Da el género
  de la fragancia y manda un par a revisión si contradice al otro lado, pero
  nunca veta ni acepta solo. `unisex` no se lee, como el "(U)" de Beauty
  Perfumes.

### Lo que cambió en el matching al sumar dperfumes (ensayo del 2026-10-21)

- **"Her", "She", "King", "Queen", "He" y "Him" son parte del nombre** en la
  identidad de la fragancia. Antes se descartaban como palabras de género y
  Burberry "Her" (2018) quedaba con la misma clave que "Burberry for Women"
  (1995): dos publicaciones con la misma clave se unen sin pasar por las
  reglas de pares. Las palabras que solo dicen el público ("Women", "Mujer",
  "Men") se siguen quitando. Cambian de clave 68 productos existentes, sin
  cambiar de id ni de publicaciones.
- **Un nombre con género contra uno sin género va a revisión** cuando solo
  los códigos de tienda muestran la línea en dos géneros. Caso real:
  "Cool Water Woman 30 ml" de dperfumes se aceptaba con el "Cool Water EDT
  30ml" de Salcobrand, que no dice el género. En las cuatro tiendas de antes
  manda a revisión 12 pares de Antonio Banderas The Icon y Blue Seduction (8
  etiquetados "same", que siguen unidos por su etiqueta); ninguna fusión
  etiquetada cambia.
- **El sufijo " – Marca" de sus nombres no se muestra** en el nombre canónico.
- **Las uniones por clave idéntica no pasan por las reglas de pares** y la
  evaluación (`src.matching.evaluate`) no las ve: con dperfumes son 57. Por eso
  la muestra de precisión se toma de los productos finales, no de los pares
  aceptados (`data/labeled/dperfumes_precision_v1.csv`).
- **Precisión medida con una muestra etiquetada a mano** (78 de los 466 pares
  finales con dperfumes, `data/labeled/dperfumes_precision_v1.csv`): reglas
  60/60, cadena 3/3, clave idéntica 14/15; estimado ponderado 99,2 %. El error
  era Animale: dperfumes vende "Animale Animale for Men" (1994, SKU 1060103) y
  "Animale for Men" (SKU 1060102), y quedaban en un producto con el "ANIMALE
  ANIMALE FOR MEN" de Beauty Perfumes. El 04/10 se habían tomado por la misma
  publicación repetida.
- **Arreglo, acotado a ese caso:**
  - dentro de una misma tienda, una palabra de la marca cuenta desde su
    segunda aparición (`store_listing_words`): si una tienda dice su marca una
    vez más, es otra fragancia. En todo el catálogo separa un solo par, el de
    Animale. Una regla general en la identidad ("la marca repetida es parte del
    nombre") tocaba 126 nombres, porque Beauty Perfumes antepone la marca
    ("PACO RABANNE PACO RABANNE PURE XS"), y se descartó;
  - una etiqueta humana "different" también separa dos grupos con la misma
    clave (antes solo vetaba el par, y la clave idéntica los volvía a unir).
- **Nombre canónico sin género:** "Davidoff Cool Water EDT 200 ml" es el nombre
  de dos productos (hombre y mujer). Ya pasaba (ver "Limitaciones del modelo
  de datos"); con dperfumes hay más casos.

## Dreams Parfums

### El listado solo muestra lo que está en stock

- **Revisado:** 2026-10-22. El sitemap trae ~1.170 productos; el catálogo
  (`/perfumes`) lista 573. Tres fichas que están en el sitemap y no en el
  listado dicen `OutOfStock` con stock 0 en sus datos estructurados; una que sí
  está listada dice `InStock` con stock 6, el mismo número que el tope de la
  cantidad en su tarjeta.
- **Cómo lo tratamos:** todo lo listado está disponible. Un perfume que se
  agota sale del listado y el loader lo desactiva como a cualquier
  publicación que falta en un scrape completo; cuando vuelve, se reactiva con
  la misma URL, producto e historial (sin precios mientras estuvo agotado).
  Así no hay que abrir cada ficha a diario. A diferencia de las otras tiendas,
  la API no muestra un perfume de Dreams "sin stock": no lo muestra.
- **Protecciones:** el total de "N de 573 productos" se compara con los
  productos vistos (exclusiones incluidas); una tarjeta que no se pudo leer
  deja la carga parcial; una página vacía antes de la última queda en el log
  con su número; el tope de 25 % de desactivaciones vale como en todas.

### Qué se excluye en el scraper

- Testers ("TESTER" en el nombre o en la URL; 81 el 22/10), desodorantes
  sueltos (9), body lotion sueltas (9) y sets con loción. Se mantienen los
  sets con desodorante. Quedan 474 cargables de 573.
- Solo se usan el listado y su paginación (`?page=N`), que su robots.txt
  permite; nunca búsqueda, filtros, orden ni rangos de precio. User agent fijo
  y 3 s entre páginas (20 páginas en ~76 s).

### Ensayo sobre una copia (2026-10-22, aún sin dperfumes cargada)

- 252 pares aceptados por reglas (211 con Beauty Perfumes, 16 Salcobrand, 14
  Preunic, 11 Maicao), 10 por clave idéntica y 6 por cadena; 249 productos
  nuevos. Ninguna publicación existente cambió de producto; evaluación de las
  tiendas anteriores sin cambios (465/465, 0 fusiones erróneas).
- Los nombres de Dreams renombran 59 productos existentes, casi todos para
  bien (agregan la concentración, acentos, "Heiress", "L'Homme"). Quedan
  algunos sufijos del desambiguador ("God is a (a)", "Sweet Tooth (carperter)"
  por un error de tipeo de la tienda) y "Agatha Look EDT 80 ml" pierde su
  género (el nombre de Dreams no lo dice).
- **Precisión medida con una muestra etiquetada a mano**
  (`data/labeled/dreamsparfums_precision_v1.csv`, 76 de los 268 pares finales,
  2026-10-22): 76/76 correctos. Reglas 30/30 con Beauty Perfumes y 10/10 con
  Salcobrand, Preunic y Maicao; clave idéntica 10/10 y cadena 6/6 (todos los de
  esos dos grupos). No incluye pares con dperfumes, que aún no estaba en la base:
  quedan para una muestra aparte.

## Palabras de formato en los nombres

### "Body splash" y "splash cologne/colonia" nombran el mismo producto

- **Revisado:** 2026-10-02, verificando las fotos de los productos, no solo
  el texto.
- **Qué pasa:** Plaisance (y posiblemente otras marcas) usa "body splash" y
  "splash cologne"/"colonia splash" como nombres intercambiables para el
  mismo producto. Ejemplos reales, todos el mismo body splash de 250 ml:
  - Maicao "Colonia Moments Splash Cologne 250 mL" = Salcobrand "Body Splash
    Moments 250ml" (lo mismo con Classic);
  - Maicao "Splash Mujer Hot Sexy EDC 250 ml" = Salcobrand "Plaisance Colonia
    Splash Hot Sexy 250ml" = Preunic "Body Splash Mujer Plaisance Hot Sexy
    250 Ml";
  - Preunic "Body Splash Plaisance Hot in Black 250 ml" = Salcobrand
    "Plaisance Splash Hot In Black 250ml".
- **La fuente confiable es la foto o la descripción de la página**, no la URL
  ni el nombre, que a veces quedan desactualizados (la URL de Preunic dice
  `splash-mujer-hot-sexy-…` y el nombre "Body Splash"). Las palabras
  "colonia"/"cologne"/"EDC" en un splash tampoco indican que sea una colonia
  distinta.
- **Regla aplicada:** "body" se ignora al comparar dos nombres que dicen
  "mist", o dos que dicen "splash" (`OPTIONAL_FORMAT_WORDS` en
  `src/matching/rules.py`; entre dos mists también se ignora "hair", por
  "Hair & Body Mist" de Petrizzio en Maicao). Medida contra todas las etiquetas, incluidas las
  3 de `data/labeled/splash_pairs_v1.csv`: 7 pares etiquetados "same" pasan
  a aceptarse y ninguna decisión etiquetada empeora.
- **Lo que no se generaliza:** un "body splash" no se compara como si fuera
  un "mist", ni al revés; solo se ignora "body" entre dos nombres del mismo
  formato. Ignorar otra palabra de formato exige antes verificar con fotos
  que las dos formas son el mismo producto y medirlo contra las etiquetas.
  Primero se creyó, solo por el texto, que Moments y Classic eran productos
  distintos; las fotos mostraron lo contrario.

### Contenido de los sets escrito distinto según la tienda

- **Revisado:** 2026-10-02, con los 57 pares de sets etiquetados en
  `data/labeled/sets_pairs_v1.csv` (fotos revisadas donde los nombres
  difieren).
- **Reglas aplicadas** (`SET_CONTENT_SPELLINGS` en `src/matching/rules.py`,
  solo al comparar nombres; los embeddings usan el texto original):
  - "BL" / "B.L." = "Body Lotion" / "Loción Corporal" (Salcobrand abrevia la
    loción corporal de los estuches de Shakira y Coral);
  - "Bálsamo After Shave" = "After Shave".
  Medidas contra todas las etiquetas: 10 sets etiquetados "same" pasan a
  aceptarse y ninguno "different". El "different" que mencionaba "B.L." (Coral
  Belle con crema contra Coral Belle con loción) queda vetado.
- **Candidata pendiente: "Perfumero" = "Perfume".** Medida, sale limpia (3
  pares "same", ninguna contradicción), pero los 3 casos son de una sola
  marca (Etienne). El riesgo real: según la marca, "perfumero" puede ser un
  atomizador de viaje **vacío** (para rellenar) o uno **con perfume** (una
  miniatura de 10 ml). En Etienne las fotos confirman que trae perfume; no se
  puede saber para otras marcas sin ver la foto de cada una. Implementarla
  cuando haya casos etiquetados de otras marcas, o acotarla a las marcas
  verificadas.
- **Efecto conocido: el set Shakira Dance queda en dos productos.** Salcobrand
  publica el mismo set dos veces con nombres distintos ("Estuche Shakira Dance
  EDT 50ml + BL 75ml" y "Pack Shakira Perfume Dance 50ml + Body Lotion 75ml"),
  el mismo patrón que el Blue Seduction 100 ml EDT. Con la regla de "BL", la
  publicación de Preunic se une al "Estuche" y la de Maicao al "Pack", y la
  regla de una publicación por tienda deja dos productos para un mismo set.
  No es una fusión errónea: es pérdida de cobertura (2 pares "same" que antes
  se aceptaban dejan de aceptarse; la regla suma 9).
- **Recordatorio:** en un set, una palabra de contenido de más suele ser otro
  set. En las etiquetas, "Desodorante" (3 de 3), "Crema" (2 de 2) y "After
  Shave" de un solo lado (3 de 4) resultaron "different". Además, los nombres
  de los sets pueden estar mal: Preunic vende como "Beso 50 ml + De beso en
  beso 10 ml" el set con stick de maquillaje (foto y SKU 595080 iguales al de
  Salcobrand).

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

### Marcas numéricas o cortas: «451 EDC 100 ml» era la colonia 4711 (16/10)

- **Qué pasaba:** la clave de marca descartaba los dígitos.
  - «4711» y «451» quedaban con clave vacía, la misma para las dos. La marca
    visible se elige entre las publicaciones de una clave, así que la colonia
    4711 de Beauty Perfumes se mostraba como «451 EDC 100 ml» (y 200 ml).
  - Una clave vacía era además un comodín en `same_brand`: casaba con
    cualquier marca. Una clave corta casaba con cualquier marca que la
    contuviera: «CR7» quedaba como `cr`, que está dentro de «Victoria's
    Secret» y «Abercrombie & Fitch».
- **Arreglo (rama `dev/brand-key`):**
  - la clave conserva los dígitos: `4711`, `451`, `cr7`, `beauty100`,
    `anfar1950`, `stallion53`;
  - una clave vacía o de hasta 3 caracteres solo coincide con la misma clave.
    Las claves más largas siguen tolerando contención y errores de tipeo
    («Banderas» = «Antonio Banderas»).
- **Medido el 16/10 sobre una copia del catálogo:**
  - cambiaron 33 claves de producto, las de esas marcas. Ninguna agrupación
    cambió y ningún `product_id` se movió. Solo cambiaron de nombre los dos
    productos 4711;
  - los candidatos bajaron de 21.367 a 13.127;
  - por reglas se dejan de aceptar 2 pares correctos: Maicao «451» frente a
    «Colonia Inglesa» (400 ml). Siguen unidos por su etiqueta, porque un par
    etiquetado se evalúa aunque no sea candidato.
- **Lo que cuesta:** «CR7» (Maicao) y «Cristiano Ronaldo» (Salcobrand) ya no
  se emparejan por reglas. Hoy no se pierde ninguno: los 6 pares posibles se
  vetaban por volumen. Si aparece el mismo producto en las dos, necesita una
  etiqueta `same`.

### Un `product_id` pasó a nombrar otro producto: Shakira Dance (15/10)

- **Qué pasó:** en la corrida 46, `cde9928c` dejó de ser el pack "Dance EDT
  50 ml + Body Lotion 75 ml" (Salcobrand sku 584149, Maicao CLMC_295429) y pasó
  a ser el estuche "Dance EDT 50 ml + Loción Corporal 75 ml" (Preunic,
  Salcobrand sku 587215 y el nuevo Maicao CLMC_585378). El pack recibió un id
  nuevo y el id del estuche (`56cc7e6b`) desapareció. El matching estaba
  bien; lo que falló fue qué id conservaba cada producto.
- **Por qué:** la publicación nueva de Maicao no dice el género, así que la
  clave del estuche perdió `female` y quedó igual a la de la fila del pack
  (`shakira|body dance lotion||`). La regla de entonces daba prioridad a la
  fila con la misma clave por sobre las publicaciones.
- **Auditoría (respaldos 08/10 y 12/10 contra el 15/10):** fue el único caso.
  No hubo fusiones, divisiones ni otras publicaciones que cambiaran de id.
- **Arreglo (rama `dev/stable-product-ids`, `assign_product_ids` en
  `src/matching/pipeline.py`):**
  1. Cada `product_id` queda con el producto que tiene sus publicaciones
     anteriores. Si quedaron repartidas, decide la regla de las divisiones de
     siempre. Si la clave cambió, se actualiza la fila (su fragancia y clave)
     y no el id.
  2. En una fusión se conserva el id con más historial de precios, luego el
     más antiguo y luego el menor.
  3. Solo un producto que no conservó ningún id puede reusar la fila con su
     clave, y solo si ninguna publicación de la corrida apuntaba a ella (un
     producto que vuelve después de salir de todas las tiendas).
  4. Las filas que cambian de clave se escriben en dos pasos dentro de la
     misma transacción (primero a una clave temporal), porque la unicidad de
     `products` no es diferible. No requiere migración.
- **Sin arreglar:** los ids de Shakira en la base siguen como quedaron el
  15/10 (el estuche en `cde9928c` y el pack en `39adddba`). La regla nueva no
  los mueve. Volver a los originales sería una corrección manual aparte.
- **Efecto restante:** un id que pierde una fusión desaparece y la API
  responde 404. Un registro de ids retirados con redirección queda pendiente,
  porque requiere una migración y un cambio en la API.

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
