import { useEffect, useState } from "react";

import { App } from "./App";
import { createApi, type Api } from "./api/client";
import { createSession, type Session } from "./auth";
import { config, loadPublicConfig, type PublicConfig } from "./config";
import { setLanguage, t } from "./i18n";
import { useLanguage } from "./useLanguage";

type Ready = { session: Session; api: Api };

/**
 * Start-up: reads GET /v1/public-config (no token), applies its language, builds the session that
 * matches its sign-in mode, then hands over to the App.
 */
export function Boot({
  base = config.api,
  fetchFn,
  makeSession = createSession,
}: {
  base?: string;
  fetchFn?: typeof fetch;
  makeSession?: (publicConfig: PublicConfig) => Session;
}) {
  useLanguage();
  const [ready, setReady] = useState<Ready | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const f = fetchFn ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));
    loadPublicConfig(base, f)
      .then((publicConfig) => {
        if (!alive) return;
        setLanguage(publicConfig.language);
        const session = makeSession(publicConfig);
        setReady({ session, api: createApi(session, base, f) });
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [base, fetchFn, makeSession]);

  if (ready) return <App session={ready.session} api={ready.api} />;
  return (
    <main className="signin">
      <h1>{t("app.title")}</h1>
      {failed ? (
        <p role="alert" className="error">
          {t("boot.failed", { url: base })}
        </p>
      ) : (
        <p className="muted">{t("boot.loading")}</p>
      )}
    </main>
  );
}
