import type { ConversationSummary } from "../api/client";
import { getLanguage, t } from "../i18n";
import { useLanguage } from "../useLanguage";

export function History({
  conversations,
  current,
  open,
}: {
  conversations: ConversationSummary[];
  current: string | null;
  open: (id: string | null) => void;
}) {
  useLanguage();
  return (
    <section aria-label={t("history.label")} className="history">
      <button
        type="button"
        className="primary"
        onClick={() => {
          open(null);
        }}
      >
        {t("history.new")}
      </button>
      <ul>
        {conversations.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              className={c.id === current ? "conversation current" : "conversation"}
              onClick={() => {
                open(c.id);
              }}
              title={new Date(c.created_at).toLocaleString(getLanguage())}
            >
              {c.title}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
