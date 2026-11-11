export default function Pagination({ total, limit, offset, onChange }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav className="pagination" aria-label="Páginas">
      <button type="button" disabled={page <= 1} onClick={() => onChange(offset - limit)}>Anterior</button>
      <span>Página {page} de {pages}</span>
      <button type="button" disabled={page >= pages} onClick={() => onChange(offset + limit)}>Siguiente</button>
    </nav>
  );
}
