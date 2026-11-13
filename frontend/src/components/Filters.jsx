import { CONCENTRATIONS, GENDERS, STORES } from "../format.js";

function CheckGroup({ legend, name, options, selected, onToggle }) {
  return (
    <fieldset className="filter-group">
      <legend>{legend}</legend>
      {Object.entries(options).map(([value, label]) => (
        <label key={value} className="check">
          <input type="checkbox" checked={selected.includes(value)} onChange={() => onToggle(name, value)} />
          <span>{label}</span>
        </label>
      ))}
    </fieldset>
  );
}

function Range({ legend, minName, maxName, values, onChange, unit }) {
  return (
    <fieldset className="filter-group">
      <legend>{legend}</legend>
      <div className="range">
        <label>
          <span className="sr-only">Mínimo</span>
          <input type="number" min="0" inputMode="numeric" placeholder="Mín." value={values[minName] ?? ""}
                 onChange={(e) => onChange(minName, e.target.value)} />
        </label>
        <span aria-hidden="true">a</span>
        <label>
          <span className="sr-only">Máximo</span>
          <input type="number" min="0" inputMode="numeric" placeholder="Máx." value={values[maxName] ?? ""}
                 onChange={(e) => onChange(maxName, e.target.value)} />
        </label>
        <span className="muted">{unit}</span>
      </div>
    </fieldset>
  );
}

// Filtros compartidos por el catálogo y la búsqueda por descripción.
export default function Filters({ values, lists, brands, onToggle, onChange, onClear }) {
  return (
    <form className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Filtros">
      {brands && (
        <label className="filter-group">
          <span className="legend">Marca</span>
          <select value={values.brand ?? ""} onChange={(e) => onChange("brand", e.target.value)}>
            <option value="">Todas las marcas</option>
            {brands.map((b) => (
              <option key={b.brand} value={b.brand}>{b.brand} ({b.products})</option>
            ))}
          </select>
        </label>
      )}
      <Range legend="Precio" minName="min_price" maxName="max_price" values={values} onChange={onChange} unit="CLP" />
      <CheckGroup legend="Para" name="gender" options={GENDERS} selected={lists.gender} onToggle={onToggle} />
      <CheckGroup legend="Concentración" name="concentration" options={CONCENTRATIONS} selected={lists.concentration} onToggle={onToggle} />
      <Range legend="Tamaño" minName="min_volume" maxName="max_volume" values={values} onChange={onChange} unit="ml" />
      <CheckGroup legend="Disponible en" name="store" options={STORES} selected={lists.store} onToggle={onToggle} />
      <button type="button" className="btn-quiet" onClick={onClear}>Quitar filtros</button>
    </form>
  );
}
