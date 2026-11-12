import { emptyFilters, type Facets, type Filters } from "../api/client";
import { t, type Key } from "../i18n";
import { useLanguage } from "../useLanguage";

type FilterKey = "repos" | "languages" | "types" | "owners";

const LABELS: Record<FilterKey, Key> = {
  owners: "filters.owners",
  types: "filters.types",
  languages: "filters.languages",
  repos: "filters.repos",
};

const ORDER = ["owners", "types", "languages", "repos"] as const;

function selectedOf(filters: Filters, key: FilterKey): string[] {
  return filters[key] ?? [];
}

export function FiltersPanel({
  facets,
  filters,
  change,
}: {
  facets: Facets;
  filters: Filters;
  change: (f: Filters) => void;
}) {
  useLanguage();
  function toggle(key: FilterKey, value: string) {
    const selected = selectedOf(filters, key);
    const next = selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value];
    change({ ...filters, [key]: next });
  }
  const active = ORDER.reduce((n, key) => n + (filters[key]?.length ?? 0), 0);
  return (
    <section aria-label={t("filters.label")} className="filters">
      <h2>
        {t("filters.label")} {active > 0 && <span className="badge">{active}</span>}
        {active > 0 && (
          <button
            type="button"
            className="link"
            onClick={() => {
              change(emptyFilters());
            }}
          >
            {t("filters.clear")}
          </button>
        )}
      </h2>
      {ORDER.map((key) => (
        <details key={key} open={key !== "repos"}>
          <summary>{t(LABELS[key])}</summary>
          <div className={key === "repos" ? "choices scrolling" : "choices"}>
            {facets[key].map((value) => (
              <label key={value}>
                <input
                  type="checkbox"
                  checked={selectedOf(filters, key).includes(value)}
                  onChange={() => {
                    toggle(key, value);
                  }}
                />
                {value}
              </label>
            ))}
          </div>
        </details>
      ))}
    </section>
  );
}
