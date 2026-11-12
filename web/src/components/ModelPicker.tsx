import type { Models } from "../api/client";
import { t } from "../i18n";
import { useLanguage } from "../useLanguage";

export type Choice = { mode: "local" | "gateway"; model: string };

/** Local by default; the gateway only offers the zero-retention models allowed today. */
export function ModelPicker({ models, choice, change }: { models: Models; choice: Choice; change: (c: Choice) => void }) {
  useLanguage();
  const remote = models.gateway.filter((m) => m.allowed);
  const value = `${choice.mode}|${choice.model}`;
  const selected = choice.mode === "gateway" ? remote.find((m) => m.alias === choice.model) : undefined;
  return (
    <div className="model-picker">
      <select
        aria-label={t("model.label")}
        value={value}
        onChange={(e) => {
          const [mode, model] = e.target.value.split("|") as [Choice["mode"], string];
          change({ mode, model });
        }}
      >
        <optgroup label={t("model.local")}>
          {models.local.map((m) => (
            <option key={m.name} value={`local|${m.name}`} disabled={!m.installed}>
              {m.installed ? m.name : t("model.notInstalled", { name: m.name })}
            </option>
          ))}
        </optgroup>
        {models.gateway_enabled && remote.length > 0 && (
          <optgroup label={t("model.gateway")}>
            {remote.map((m) => (
              <option key={m.alias} value={`gateway|${m.alias}`}>
                {m.alias} ({m.provider})
              </option>
            ))}
          </optgroup>
        )}
      </select>
      {selected && (
        <p className="warning" role="status">
          {t("model.remoteBanner", { provider: selected.provider, date: selected.verified_on })}
          {selected.warning && ` ${selected.warning}`}
        </p>
      )}
    </div>
  );
}
