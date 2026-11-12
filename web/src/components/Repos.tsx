import { useCallback, useEffect, useState } from "react";

import { reason, type Api, type IndexStatus, type Repo } from "../api/client";
import type { Session } from "../auth";
import { getLanguage, t, tn } from "../i18n";
import { useLanguage } from "../useLanguage";

export function Repos({ api, session, admin }: { api: Api; session: Session; admin: boolean }) {
  const language = useLanguage();
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [status, setStatus] = useState<IndexStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    void Promise.all([api.GET("/v1/repos"), api.GET("/v1/index")]).then(([r, s]) => {
      if (r.data) setRepos(r.data);
      if (s.data) setStatus(s.data);
    });
  }, [api]);

  useEffect(load, [load]);

  useEffect(() => {
    if (!status?.running) return;
    const timer = setInterval(load, 5000);
    return () => {
      clearInterval(timer);
    };
  }, [status?.running, load]);

  async function reindex() {
    setError(null);
    let answer = await api.POST("/v1/index");
    if (answer.response.status === 403) {
      // Admin action: in OIDC mode the issuer must have seen a recent login.
      await session.reauthenticate();
      answer = await api.POST("/v1/index");
    }
    if (answer.data) setStatus(answer.data);
    else setError(reason(answer.error, answer.response.status));
  }

  const total = repos?.reduce((n, r) => n + r.chunks, 0) ?? 0;
  return (
    <section aria-label={t("repos.label")} className="repos">
      <h2>
        {repos
          ? tn("repos.summary", repos.length, { chunks: total.toLocaleString(language) })
          : t("repos.loading")}
      </h2>
      {status && (
        <p className={status.running ? "warning" : "muted"} role="status">
          {t(status.running ? "repos.running" : "repos.last", { message: status.message ?? t("repos.never") })}
        </p>
      )}
      {admin && (
        <button type="button" className="primary" disabled={status?.running} onClick={() => void reindex()}>
          {t("repos.update")}
        </button>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {repos && (
        <table>
          <thead>
            <tr>
              <th>{t("repos.col.repo")}</th>
              <th>{t("repos.col.files")}</th>
              <th>{t("repos.col.chunks")}</th>
              <th>{t("repos.col.commit")}</th>
              <th>{t("repos.col.indexed")}</th>
            </tr>
          </thead>
          <tbody>
            {repos.map((r) => (
              <tr key={r.key}>
                <td>
                  {r.key}
                  {r.local_only && (
                    <span className="badge" title={t("repos.localTitle")}>
                      {t("repos.local")}
                    </span>
                  )}
                </td>
                <td>{r.files}</td>
                <td>{r.chunks}</td>
                <td>
                  <code>{r.commit.slice(0, 7)}</code>
                </td>
                <td>{new Date(r.indexed_at).toLocaleDateString(getLanguage())}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
