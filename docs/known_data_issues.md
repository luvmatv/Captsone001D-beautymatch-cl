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
