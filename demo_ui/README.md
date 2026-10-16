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

## Limitaciones

- La API no tiene búsqueda por texto, solo filtro por marca exacta. El campo
  «Buscar» descarga el catálogo de `GET /products` en páginas de 100 y filtra
  en el navegador. La página lo avisa.
- La dirección de la API está fija en el archivo (`http://127.0.0.1:8000`).
