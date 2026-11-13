import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

export const LIST_KEYS = ["gender", "concentration", "store"];
export const VALUE_KEYS = ["brand", "min_price", "max_price", "min_volume", "max_volume"];

// Filtros guardados en la URL (se pueden compartir y el botón "atrás" funciona).
export function useFilters() {
  const [params, setParams] = useSearchParams();
  const lists = useMemo(() => Object.fromEntries(LIST_KEYS.map((k) => [k, params.getAll(k)])), [params]);
  const values = useMemo(() => Object.fromEntries([...VALUE_KEYS, "q", "sort", "offset"].map((k) => [k, params.get(k) ?? ""])), [params]);

  const update = (mutate) => {
    const next = new URLSearchParams(params);
    mutate(next);
    next.delete("offset"); // cualquier cambio de filtro vuelve a la primera página
    setParams(next, { replace: false });
  };
  return {
    params, lists, values,
    toggle: (name, value) => update((next) => {
      const current = next.getAll(name);
      next.delete(name);
      (current.includes(value) ? current.filter((v) => v !== value) : [...current, value]).forEach((v) => next.append(name, v));
    }),
    change: (name, value) => update((next) => (value === "" ? next.delete(name) : next.set(name, value))),
    clear: () => update((next) => [...LIST_KEYS, ...VALUE_KEYS].forEach((k) => next.delete(k))),
    setOffset: (offset) => {
      const next = new URLSearchParams(params);
      offset > 0 ? next.set("offset", offset) : next.delete("offset");
      setParams(next);
      window.scrollTo({ top: 0 });
    },
  };
}

export function apiFilters(lists, values) {
  const out = { ...lists };
  for (const k of VALUE_KEYS) if (values[k]) out[k] = values[k];
  return out;
}

export function useDebounced(value, ms = 400) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}
