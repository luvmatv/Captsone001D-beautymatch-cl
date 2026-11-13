const clp = new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP" });
const dateTime = new Intl.DateTimeFormat("es-CL", { dateStyle: "medium", timeStyle: "short" });
const shortDate = new Intl.DateTimeFormat("es-CL", { day: "numeric", month: "short" });

export const money = (value) => (value === null || value === undefined ? "Sin precio" : clp.format(value));
export const perMl = (value) => (value === null || value === undefined ? null : `${clp.format(Math.round(value))}/ml`);
export const when = (iso) => (iso ? dateTime.format(new Date(iso)) : "");
export const day = (iso) => shortDate.format(new Date(iso));

export const STORES = {
  preunic: "Preunic",
  maicao: "Maicao",
  salcobrand: "Salcobrand",
  beautyperfumes: "Beauty Perfumes",
  dperfumes: "dperfumes",
  dreamsparfums: "Dreams Parfums",
};
export const storeName = (key) => STORES[key] ?? key;

export const CONCENTRATIONS = {
  parfum: "Parfum",
  edp: "Eau de parfum",
  edt: "Eau de toilette",
  cologne: "Colonia",
  eau_fraiche: "Eau fraîche",
  other: "Otra",
};
export const CONCENTRATION_SHORT = { parfum: "Parfum", edp: "EDP", edt: "EDT", cologne: "Colonia", eau_fraiche: "Eau fraîche", other: "Otra" };

export const GENDERS = { female: "Mujer", male: "Hombre", unisex: "Unisex o sin indicar" };

export const PRESENTATIONS = {
  full_bottle: "Frasco",
  tester: "Tester",
  travel_set: "Set",
  miniature: "Miniatura",
  refill: "Recarga",
};

export const SORTS = {
  relevance: "Más relevantes",
  name: "Nombre (A-Z)",
  price_asc: "Menor precio",
  price_desc: "Mayor precio",
  discount: "Mayor descuento",
  price_per_ml: "Menor precio por ml",
};

// Colores de las líneas del historial, uno por tienda (distinguibles también por la leyenda).
export const STORE_COLORS = {
  preunic: "#5B3F8C",
  maicao: "#C98A00",
  salcobrand: "#1D7A52",
  beautyperfumes: "#B4416B",
  dperfumes: "#2F6DB5",
  dreamsparfums: "#6B6578",
};
