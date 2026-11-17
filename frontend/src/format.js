const clp = new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP" });
const dateTime = new Intl.DateTimeFormat("es-CL", { dateStyle: "medium", timeStyle: "short" });
const shortDate = new Intl.DateTimeFormat("es-CL", { day: "numeric", month: "short" });

export const money = (value) => (value === null || value === undefined ? "Sin precio" : clp.format(value));
export const perMl = (value) => (value === null || value === undefined ? null : `${clp.format(Math.round(value))}/ml`);
export const when = (iso) => (iso ? dateTime.format(new Date(iso)) : "");
export const day = (iso) => shortDate.format(new Date(iso));

// Días de calendario de Chile entre una lectura y hoy (la corrida diaria es de mañana, hora de Chile).
const chileDay = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Santiago" });
const dayNumber = (date) => Date.parse(chileDay.format(date)) / 86400000;
export const daysAgo = (iso, now = new Date()) => Math.round(dayNumber(now) - dayNumber(new Date(iso)));
export const readOn = (iso, now = new Date()) => {
  const days = daysAgo(iso, now);
  if (days <= 0) return "leído hoy";
  if (days === 1) return "leído ayer";
  return `leído hace ${days} días`;
};

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

// El nombre sin la marca delante: la marca va en su propia línea encima.
export const nameWithoutBrand = (p) =>
  p.brand && p.canonical_name.startsWith(`${p.brand} `) ? p.canonical_name.slice(p.brand.length + 1) : p.canonical_name;

// Marca y fragancia, sin concentración ni tamaño (para titulares: "Lattafa Yara").
export const shortName = (p) =>
  p.canonical_name.replace(/\s+(EDP|EDT|EDC|Parfum|Eau de \w+|Colonia|Body Mist|Splash)\b.*$/i, "").replace(/\s+\d+\s?ml$/i, "");

// La misma foto de la tienda pedida más grande cuando su servidor lo permite
// (Dreams Parfums entrega 306x172 por defecto y acepta /resize/1000/1000).
export const bigImage = (url) => (url ? url.replace(/\/resize\/\d+\/\d+/, "/resize/1000/1000") : url);

// La mejor foto entre las publicaciones de un producto: primero las tiendas que entregan fotos grandes.
const PHOTO_ORDER = ["dperfumes", "preunic", "beautyperfumes", "salcobrand", "dreamsparfums"];
const rank = (store) => (PHOTO_ORDER.includes(store) ? PHOTO_ORDER.indexOf(store) : PHOTO_ORDER.length);
export const bestImage = (product) => {
  const byStore = (product.prices ?? []).filter((x) => x.image_url)
    .sort((a, b) => rank(a.store) - rank(b.store));
  return bigImage(byStore[0]?.image_url ?? product.image_url);
};
