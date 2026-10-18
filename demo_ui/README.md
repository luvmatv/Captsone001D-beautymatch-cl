# Demo provisional de interfaz

Página única (HTML, CSS y JavaScript puro, sin dependencias) para mostrar el
avance del equipo de datos contra la API local. **No es el frontend real**:
ese lo hace el equipo de frontend. Solo hace `GET`.

## Cómo verla

1. Levantar la API desde la raíz del repositorio. Las variables son las de
   `.env.example`, con la contraseña del contenedor:

   ```powershell
   copy .env.example .env    # completar PGPASSWORD=dev
   uvicorn src.api.main:app --env-file .env
   ```

2. En otra terminal, servir esta carpeta en el puerto 5173, que es el origen
   que permite el CORS (`API_CORS_ORIGINS=http://localhost:5173`):

   ```powershell
   cd demo_ui
   python -m http.server 5173
   ```

3. Abrir **http://localhost:5173**. Tiene que ser `localhost` y no
   `127.0.0.1`, porque el CORS compara el origen exacto.

## Búsqueda

- El campo «Buscar» usa la búsqueda de la API: `GET /products?q=…`. No
  distingue mayúsculas ni acentos, y con varias palabras deben estar todas.
- Busca solo al dejar de escribir (300 ms) o al pulsar «Buscar», y no repite la
  consulta si el texto no cambió.
- Se combina con la marca exacta (`brand`) y con la paginación.
- Más de 100 caracteres o de 10 palabras: aparece un aviso bajo el campo y no
  se consulta. Si la API responde `422` igual, se muestra el mismo tipo de aviso.
- Requiere la API con la búsqueda, es decir, main desde 64f73a4.

## Limitaciones

- La dirección de la API está fija en el archivo (`http://127.0.0.1:8000`).
