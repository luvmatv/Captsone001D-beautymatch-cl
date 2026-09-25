# Maicao scraper POC

Category URL: `https://www.maicao.cl/perfumes-y-fragancias/`

The catalog uses twelve products per page and offset pagination. The first page exposes offsets from `0` to `300`, which corresponds to an estimated 312 products across 26 pages. The scraper verifies the final page by requesting sequential offsets and stopping when it receives fewer than twelve products.

Product links contain a `CLMC_` identifier. The POC extracts brand, name, current price, previous price, volume, concentration, URL, image URL, and online availability.
