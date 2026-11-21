// Logo de Match IA: un destello de cuatro puntas (curvas cóncavas entre las puntas) con una etiqueta "IA"
// abajo a la derecha. Dibujo propio, en el color de acento del sitio. Decorativo: el nombre va siempre en texto.
export default function MatchIaMark({ className = "" }) {
  return (
    <svg viewBox="0 0 30 26" className={`match-mark ${className}`} aria-hidden="true" focusable="false">
      <path className="match-mark-star"
            d="M11 1.5C11.7 6.6 15.4 10.3 20.5 11 15.4 11.7 11.7 15.4 11 20.5 10.3 15.4 6.6 11.7 1.5 11 6.6 10.3 10.3 6.6 11 1.5Z" />
      <path className="match-mark-star" opacity=".55"
            d="M21.5 1.5C21.8 3.5 23 4.7 25 5 23 5.3 21.8 6.5 21.5 8.5 21.2 6.5 20 5.3 18 5 20 4.7 21.2 3.5 21.5 1.5Z" />
      <rect className="match-mark-tag" x="15.5" y="15" width="13.5" height="10" rx="3.2" />
      <text className="match-mark-text" x="22.25" y="22.4" textAnchor="middle">IA</text>
    </svg>
  );
}
