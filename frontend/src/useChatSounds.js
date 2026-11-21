import { useCallback, useRef, useState } from "react";

// Sonidos del chat de Match IA, generados con Web Audio (sin archivos).
// - Solo suenan tras una acción de la persona: el AudioContext se crea en el primer envío (un clic o Enter),
//   nunca al cargar la página.
// - Volumen bajo y envolvente suave (sube en 6 ms, cae exponencialmente), así no hay clics ni distorsión.
// - Silenciar se recuerda en localStorage; si el navegador no deja guardar, funciona igual en esta visita.
const KEY = "bm-match-ia-muted";

function readMuted() {
  try { return window.localStorage.getItem(KEY) === "1"; } catch { return false; }
}
function writeMuted(value) {
  try { window.localStorage.setItem(KEY, value ? "1" : "0"); } catch { /* sin almacenamiento: solo esta visita */ }
}

// Un "pop": seno con un pequeño deslizamiento de tono y una envolvente corta.
function pop(ctx, { from, to, peak, length }) {
  const t = ctx.currentTime + 0.01;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "sine";
  osc.frequency.setValueAtTime(from, t);
  osc.frequency.exponentialRampToValueAtTime(to, t + length * 0.6);
  gain.gain.setValueAtTime(0.0001, t);
  gain.gain.exponentialRampToValueAtTime(peak, t + 0.006);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + length);
  osc.connect(gain).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + length + 0.02);
  osc.onended = () => { osc.disconnect(); gain.disconnect(); };
}

export function useChatSounds() {
  const [muted, setMuted] = useState(readMuted);
  const ctxRef = useRef(null);

  const context = () => {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!ctxRef.current) ctxRef.current = new Ctx();
    if (ctxRef.current.state === "suspended") ctxRef.current.resume().catch(() => {});
    return ctxRef.current;
  };

  const play = useCallback((kind) => {
    if (muted) return;
    try {
      const ctx = context();
      if (!ctx) return;
      if (kind === "send") pop(ctx, { from: 520, to: 760, peak: 0.05, length: 0.09 });
      else pop(ctx, { from: 360, to: 270, peak: 0.035, length: 0.16 });
    } catch { /* sin audio: el chat sigue igual */ }
  }, [muted]);

  const toggleMuted = useCallback(() => {
    setMuted((m) => { writeMuted(!m); return !m; });
  }, []);

  return { muted, toggleMuted, playSend: () => play("send"), playReply: () => play("reply") };
}
