import { Fragment, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import ProductCard from "../components/ProductCard.jsx";

const EXAMPLES = [
  "Busco algo dulce de vainilla para mujer, hasta 30 mil",
  "Un perfume fresco para hombre para el verano",
  "Algo parecido a Dior Sauvage pero más barato",
  "Un regalo para mi mamá, le gustan los florales",
];
const MAX_MESSAGES = 30;

// Convierte **negritas** en <strong>.
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part
  );
}

// Muestra la respuesta del sommelier: párrafos y listas con guiones.
function Reply({ text }) {
  const blocks = [];
  for (const line of text.split("\n")) {
    const item = line.match(/^\s*[-*•]\s+(.*)/);
    if (item) {
      const last = blocks[blocks.length - 1];
      if (last?.type === "list") last.items.push(item[1]);
      else blocks.push({ type: "list", items: [item[1]] });
    } else if (line.trim()) {
      blocks.push({ type: "p", text: line.trim() });
    }
  }
  return blocks.map((block, i) =>
    block.type === "list" ? (
      <ul key={i}>{block.items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ul>
    ) : (
      <p key={i}>{inline(block.text)}</p>
    )
  );
}

function errorText(error) {
  if (error.status === 503) return "El sommelier no está disponible en este momento (puede que se haya agotado la cuota diaria). Intenta de nuevo en unos minutos.";
  if (error.status === 0) return error.message;
  return "Algo falló al consultar al sommelier. Intenta de nuevo.";
}

export default function Sommelier() {
  // Cada mensaje: { role: "user" | "assistant", content, products? }
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const endRef = useRef(null);
  const controller = useRef(null);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [messages, loading]);
  useEffect(() => () => controller.current?.abort(), []);

  async function send(content) {
    const question = content.trim();
    if (!question || loading) return;
    const history = [...messages, { role: "user", content: question }].slice(-MAX_MESSAGES);
    setMessages(history);
    setText("");
    setError(null);
    setLoading(true);
    controller.current = new AbortController();
    try {
      const data = await api.chat(history.map(({ role, content }) => ({ role, content })), {
        signal: controller.current.signal,
      });
      setMessages([...history, { role: "assistant", content: data.reply, products: data.products }]);
    } catch (err) {
      if (err.name === "AbortError") return;
      setError(err);
      setMessages(history.slice(0, -1));  // se quita la pregunta para poder reenviarla
      setText(question);
    } finally {
      setLoading(false);
    }
  }

  function restart() {
    controller.current?.abort();
    setMessages([]);
    setError(null);
    setLoading(false);
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Sommelier</h1>
        <p className="hero-lead">
          Cuéntale qué te gusta, para quién es o tu presupuesto, y te recomienda perfumes del catálogo con el mejor
          precio. Las notas olfativas que menciona son orientativas.
        </p>
      </header>

      <section className="chat" aria-label="Conversación con el sommelier">
        {messages.length === 0 && (
          <div className="chips" aria-label="Ejemplos">
            {EXAMPLES.map((e) => (
              <button key={e} type="button" className="chip" onClick={() => send(e)}>{e}</button>
            ))}
          </div>
        )}

        <ol className="chat-log" aria-live="polite">
          {messages.map((m, i) => (
            <Fragment key={i}>
              <li className={`chat-msg chat-${m.role}`}>
                {m.role === "assistant" ? <Reply text={m.content} /> : <p>{m.content}</p>}
              </li>
              {m.products?.length > 0 && (
                <li className="chat-products">
                  <div className="grid grid-small">
                    {m.products.map((p) => <ProductCard key={p.product_id} product={p} />)}
                  </div>
                </li>
              )}
            </Fragment>
          ))}
          {loading && <li className="chat-msg chat-assistant chat-typing" role="status">Buscando en el catálogo…</li>}
        </ol>

        {error && (
          <div className="status status-error" role="alert">
            <p>{errorText(error)}</p>
          </div>
        )}

        <form className="search chat-form" onSubmit={(e) => { e.preventDefault(); send(text); }}>
          <label htmlFor="chat-input" className="sr-only">Escribe tu mensaje</label>
          <input id="chat-input" type="text" maxLength={2000} value={text} disabled={loading}
                 onChange={(e) => setText(e.target.value)} placeholder="Ej.: algo fresco para el día, hasta 40 mil" />
          <button type="submit" disabled={loading || !text.trim()}>Enviar</button>
        </form>
        {messages.length > 0 && (
          <button type="button" className="btn-quiet chat-restart" onClick={restart}>Nueva conversación</button>
        )}
      </section>
    </div>
  );
}
