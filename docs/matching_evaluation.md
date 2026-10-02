# Evaluación del matching

Precisión de los matches automáticos medida contra las etiquetas humanas de
`data/labeled/*.csv`. Se mide con:

```
python -m src.matching.evaluate
```

El script decide los pares **sin** aplicar las etiquetas (si no, se estarían
calificando a sí mismas) y cuenta como aceptado todo par de publicaciones que
termina en el mismo producto, incluidos los unidos por cadena (P-M + M-S ⇒ P-S).

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
