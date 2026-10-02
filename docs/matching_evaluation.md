# Evaluación del matching

Precisión de los matches automáticos medida contra las etiquetas humanas de
`data/labeled/*.csv`. Se mide con:

```
python -m src.matching.evaluate
```

El script decide los pares **sin** aplicar las etiquetas (si no, se estarían
calificando a sí mismas) y cuenta como aceptado todo par de publicaciones que
termina en el mismo producto, incluidos los unidos por cadena (P-M + M-S ⇒ P-S).

## 2026-10-02 (después de las reglas de contenido de sets): 410/410 = 100 %, exacta

Con las reglas que leen igual el contenido de los sets escrito distinto
(commit `54d3bdf`): "BL" / "B.L." = "Body Lotion" / "Loción Corporal" y
"Bálsamo After Shave" = "After Shave"; y con las 57 etiquetas de
`sets_pairs_v1.csv` (41 same, 16 different).

| Par de tiendas | Correctos / aceptados | Unidos por cadena |
|---|---|---|
| Preunic–Maicao | 122/122 = 100 % | 1 |
| Preunic–Salcobrand | 181/181 = 100 % | 0 |
| Maicao–Salcobrand | 107/107 = 100 % | 1 |
| **Total** | **410/410 = 100 %** | |

- **Exacta:** todos los pares aceptados estaban etiquetados. Sin fusiones
  erróneas y sin grupos inconsistentes. 1185 publicaciones evaluadas.
- **Qué cambió respecto de 403/403:** 9 sets etiquetados "same" pasaron de
  revisión a aceptación automática (Shakira, Coral Belle, Diavolo,
  Mediterráneo, Seduction X). Se perdieron 2 pares "same" que antes se
  aceptaban, ambos del set Shakira Dance: Salcobrand lo publica dos veces
  ("Estuche … BL" y "Pack … Body Lotion") y la regla de una publicación por
  tienda lo deja en dos productos (ver [known_data_issues.md](known_data_issues.md),
  "Contenido de los sets escrito distinto según la tienda"). No es una fusión
  errónea, es pérdida de cobertura. Neto: +7. El set Coral Belle con crema,
  etiquetado "different", pasó de revisión a veto.
- **Grupos con una tienda repetida:** 9 (antes 8). El nuevo es Mediterráneo,
  que Salcobrand publica dos veces con la misma clave de identidad: el mismo
  producto dos veces, no un error.
- **Cobertura ese día**, entre los pares etiquetados "same": 52 seguían en
  la cola de revisión, 5 se perdieron por la regla de una publicación por
  tienda (3 del set Shakira Dance) y 17 no se evaluaron porque una de sus
  publicaciones estaba inactiva. La cola de revisión bajó de 171 a 161 pares.

## 2026-10-02 (después de la regla de "hair" entre mists): 403/403 = 100 %, exacta

Con la regla que ignora "hair" entre dos nombres que dicen "mist" (commit
`483539c`): Maicao "Hair & Body Mist" = Preunic "Body Mist" de Petrizzio.

| Par de tiendas | Correctos / aceptados | Unidos por cadena |
|---|---|---|
| Preunic–Maicao | 123/123 = 100 % | 1 |
| Preunic–Salcobrand | 173/173 = 100 % | 0 |
| Maicao–Salcobrand | 107/107 = 100 % | 1 |
| **Total** | **403/403 = 100 %** | |

- **Exacta:** todos los pares aceptados estaban etiquetados. Sin fusiones
  erróneas y sin grupos inconsistentes. 1185 publicaciones evaluadas.
- **Qué cambió respecto de 400/400:** 3 pares de Petrizzio (Ready To Party,
  Caramel, Take a Break) pasaron de revisión a aceptación automática. Están
  etiquetados "misma fragancia, tamaño desconocido"; hoy los dos lados dicen
  200 ml, así que cuentan como correctos. Además, 2 pares sin etiquetar de
  Petrizzio (Carnival / Enjoy The Carnival, Vacation / Vacation Mode On)
  pasaron de veto a revisión, no a aceptación. Ningún par etiquetado empeoró.
  La cola de revisión bajó de 172 a 171 pares.
- **Cobertura ese día**, entre los pares etiquetados "same": 21 seguían en la
  cola de revisión, 2 se perdieron por la regla de una publicación por tienda
  y 17 no se evaluaron porque una de sus publicaciones estaba inactiva.

## 2026-10-02 (después de la regla de splash): 400/400 = 100 %, exacta

Con la regla que ignora "body" entre dos nombres que dicen "splash" (commit
`0c28550`; ver [known_data_issues.md](known_data_issues.md), "Palabras de
formato en los nombres") y las 3 etiquetas de `splash_pairs_v1.csv`.

| Par de tiendas | Correctos / aceptados | Unidos por cadena |
|---|---|---|
| Preunic–Maicao | 120/120 = 100 % | 1 |
| Preunic–Salcobrand | 173/173 = 100 % | 0 |
| Maicao–Salcobrand | 107/107 = 100 % | 1 |
| **Total** | **400/400 = 100 %** | |

- **Exacta:** todos los pares aceptados estaban etiquetados. Sin fusiones
  erróneas y sin grupos inconsistentes.
- **Datos:** 1185 publicaciones evaluadas (una menos que en la medición
  anterior: una publicación de Preunic se desactivó entre las dos).
- **Qué cambió respecto de 393/393:** 7 pares etiquetados "same" pasaron de
  revisión a aceptación automática (body splash / splash de Plaisance e
  Itzy). Ningún par etiquetado empeoró y no cambió ningún veto. La cola de
  revisión bajó de 179 a 172 pares.
- **Cobertura ese día**, entre los pares etiquetados "same": 21 seguían en
  la cola de revisión, 2 se perdieron por la regla de una publicación por
  tienda y 17 no se evaluaron porque una de sus publicaciones estaba inactiva.

## 2026-10-02: 393/393 = 100 %, exacta en las tres combinaciones

| Par de tiendas | Correctos / aceptados | Unidos por cadena |
|---|---|---|
| Preunic–Maicao | 118/118 = 100 % | 1 |
| Preunic–Salcobrand | 170/170 = 100 % | 0 |
| Maicao–Salcobrand | 105/105 = 100 % | 1 |
| **Total** | **393/393 = 100 %** | |

- **Exacta, no estimada:** todos los pares aceptados ese día estaban etiquetados.
  Sin fusiones erróneas y sin grupos inconsistentes (8 grupos tienen la misma
  publicación repetida en una tienda, con el mismo producto).
- **Válida solo para los datos de esa fecha** (1186 publicaciones evaluadas de las
  tres tiendas). Cada corrida diaria puede traer pares aceptados nuevos sin etiquetar;
  desde ahí la cifra vuelve a ser una estimación sobre lo etiquetado.
- **Lo que no mide:** la cobertura. Ese día, entre los pares etiquetados "same":
  25 seguían en la cola de revisión, 2 se perdieron por la regla de una
  publicación por tienda (Salcobrand publica dos veces el mismo Blue Seduction
  100 ml EDT) y 17 no se evaluaron porque una de sus publicaciones estaba
  inactiva.
- **Al volver a medir:** si quedan pares aceptados sin etiquetar, no son una
  muestra al azar (son los que agregaron reglas o datos nuevos), así que no se
  debe calcular una cota estadística con ellos; el peor caso es contarlos como
  errores.
