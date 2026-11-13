import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="page status">
      <h1>Esta página no existe</h1>
      <p>Revisa la dirección o vuelve al catálogo para buscar tu perfume.</p>
      <Link to="/" className="btn">Ir al catálogo</Link>
    </div>
  );
}
