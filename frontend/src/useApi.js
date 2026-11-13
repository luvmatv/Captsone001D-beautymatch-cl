import { useEffect, useState } from "react";

// Llama a la API cada vez que cambian las dependencias y cancela la llamada anterior.
export function useApi(load, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ data: s.data, error: null, loading: true }));
    load({ signal: controller.signal })
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error) => {
        if (error.name !== "AbortError") setState({ data: null, error, loading: false });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}
