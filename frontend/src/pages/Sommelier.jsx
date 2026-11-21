import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { SOMMELIER_AVAILABLE, api } from "../api.js";
import ProductCard from "../components/ProductCard.jsx";
import MatchIaMark from "../components/MatchIaMark.jsx";
import { useChatSounds } from "../useChatSounds.js";

// Match IA: el asistente de perfumes (en el backend y en las variables de entorno sigue llamándose "sommelier").
const SUBTITLE = "Tu asesor de perfumes. Cuéntale qué buscas y te recomienda los mejores precios de hoy.";
const BUSY = "Match IA está muy ocupado, intenta en un momento.";

function PageHead() {
  useEffect(() => {
    document.title = "Match IA | BeautyMatch CL";
    return () => { document.title = "BeautyMatch CL"; };
  }, []);
  return (
    <header className="page-head">
      <h1 className="match-title"><MatchIaMark className="match-title-mark" />Match IA</h1>
      <p className="hero-lead">{SUBTITLE}</p>
    </header>
  );
}

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

// Muestra la respuesta de Match IA: párrafos y listas con guiones.
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
  // 503: el backend dice si está muy ocupado (tardó demasiado) o sin cuota. Sus textos nombran al
  // "sommelier": aquí se muestran con el nombre nuevo, sin tocar el backend.
  if (error.status === 503) {
    if (!error.serverMessage) return "Match IA no está disponible en este momento. Intenta de nuevo en unos minutos.";
    if (/muy ocupado/i.test(error.message)) return BUSY;
    return error.message.replace(/el sommelier/i, "Match IA");
  }
  if (error.status === 0) return error.message;
  return "Algo falló al consultar a Match IA. Intenta de nuevo.";
}

// Sin VITE_SOMMELIER_URL en la versión publicada: Match IA todavía no está en línea.
function ComingSoon() {
  return (
    <div className="page">
      <PageHead />
      <section className="soon" aria-labelledby="soon-title">
        <p className="soon-tag">Disponible pronto</p>
        <h2 id="soon-title">Estamos terminando de publicarlo.</h2>
        <p>Mientras tanto, describe el aroma que buscas o explora el catálogo con sus filtros.</p>
        <div className="soon-actions">
          <Link className="btn" to="/describir">Buscar por descripción</Link>
          <Link className="link-arrow" to="/catalogo">Explorar el catálogo</Link>
        </div>
      </section>
    </div>
  );
}

export default function Sommelier() {
  return SOMMELIER_AVAILABLE ? <SommelierChat /> : <ComingSoon />;
}

function SommelierChat() {
  // Cada mensaje: { role: "user" | "assistant", content, products? }
  const [messages, setMessages] = useState([]);
  // ?q= viene del botón de la ficha: la pregunta queda escrita, la persona decide si la envía
  const [params] = useSearchParams();
  const [text, setText] = useState(() => (params.get("q") ?? "").slice(0, 2000));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const endRef = useRef(null);
  const sounds = useChatSounds();
  const controller = useRef(null);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [messages, loading]);
  useEffect(() => () => controller.current?.abort(), []);

  async function send(content) {
    const question = content.trim();
    if (!question || loading) return;
    const history = [...messages, { role: "user", content: question }].slice(-MAX_MESSAGES);
    setMessages(history);
    sounds.playSend();
    setText("");
    setError(null);
    setLoading(true);
    controller.current = new AbortController();
    try {
      const data = await api.chat(history.map(({ role, content }) => ({ role, content })), {
        signal: controller.current.signal,
      });
      setMessages([...history, { role: "assistant", content: data.reply, products: data.products }]);
      sounds.playReply();
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
      <PageHead />

      <section className="chat" aria-label="Conversación con Match IA">
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
              {m.role === "assistant" ? (
                <li className="chat-ai">
                  <span className="chat-avatar"><MatchIaMark /></span>
                  <div className="chat-msg chat-assistant"><Reply text={m.content} /></div>
                </li>
              ) : <li className="chat-msg chat-user"><p>{m.content}</p></li>}
              {m.products?.length > 0 && (
                <li className="chat-products">
                  <div className="grid grid-small">
                    {m.products.map((p) => <ProductCard key={p.product_id} product={p} />)}
                  </div>
                </li>
              )}
            </Fragment>
          ))}
          {loading && (
            <li className="chat-ai" role="status">
              <span className="chat-avatar"><MatchIaMark /></span>
              <div className="chat-msg chat-assistant chat-typing">Buscando en el catálogo…</div>
            </li>
          )}
        </ol>

        {error && (
          <div className="status status-error" role="alert">
            <p>{errorText(error)}</p>
            {text && <p className="status-hint">Tu pregunta quedó escrita abajo para enviarla de nuevo.</p>}
          </div>
        )}

        <form className="search chat-form" onSubmit={(e) => { e.preventDefault(); send(text); }}>
          <label htmlFor="chat-input" className="sr-only">Escribe tu mensaje</label>
          <input id="chat-input" type="text" maxLength={2000} value={text} disabled={loading}
                 onChange={(e) => setText(e.target.value)} placeholder="Ej.: algo fresco para el día, hasta 40 mil" />
          <button type="submit" disabled={loading || !text.trim()}>Enviar</button>
        </form>
        <div className="chat-tools">
          {messages.length > 0 && (
            <button type="button" className="btn-quiet" onClick={restart}>Nueva conversación</button>
          )}
          {/* Sonidos al enviar y al recibir: se pueden silenciar y la elección se recuerda */}
          <button type="button" className="btn-quiet chat-sound" aria-pressed={sounds.muted} onClick={sounds.toggleMuted}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" />
              {sounds.muted ? <path d="m16 9.5 5 5m0-5-5 5" /> : <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />}
            </svg>
            {sounds.muted ? "Sonido desactivado" : "Sonido activado"}
          </button>
        </div>
      </section>
    </div>
  );
}
