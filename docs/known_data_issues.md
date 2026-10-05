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
