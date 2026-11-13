// Mensajes de carga, error y vacío, con instrucciones concretas.
export function Loading({ label = "Cargando precios…" }) {
  return <p className="status" role="status">{label}</p>;
}

export function ErrorMessage({ error, onRetry }) {
  let text = error?.message || "Algo falló al pedir los datos.";
  if (error?.status === 503) text = "La base de datos no responde en este momento. Intenta de nuevo en unos segundos.";
  if (error?.status === 422) text = "Algún filtro tiene un valor no válido (por ejemplo, un mínimo mayor que el máximo). Revisa los filtros.";
  return (
    <div className="status status-error" role="alert">
      <p>{text}</p>
      {onRetry && <button type="button" className="btn-quiet" onClick={onRetry}>Reintentar</button>}
    </div>
  );
}

export function Empty({ children }) {
  return <div className="status">{children}</div>;
}
