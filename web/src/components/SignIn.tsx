import { useState } from "react";

import type { AuthMode } from "../auth";
import { t } from "../i18n";
import { useLanguage } from "../useLanguage";

export function SignIn({
  mode,
  error,
  signIn,
}: {
  mode: AuthMode;
  error: string | null;
  signIn: (secret?: string) => void;
}) {
  useLanguage();
  const [secret, setSecret] = useState("");
  return (
    <main className="signin">
      <h1>{t("app.title")}</h1>
      <p>{t("app.tagline")}</p>
      {mode === "oidc" ? (
        <button
          type="button"
          className="primary"
          onClick={() => {
            signIn();
          }}
        >
          {t("signin.button")}
        </button>
      ) : (
        <form
          className="token-form"
          onSubmit={(e) => {
            e.preventDefault();
            const value = secret.trim();
            if (!value) return;
            setSecret("");
            signIn(value);
          }}
        >
          <label htmlFor="api-token">{t("signin.tokenLabel")}</label>
          <input
            id="api-token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            aria-describedby="api-token-help"
            value={secret}
            onChange={(e) => {
              setSecret(e.target.value);
            }}
          />
          <p id="api-token-help" className="muted">
            {t("signin.tokenHelp")}
          </p>
          <button type="submit" className="primary" disabled={!secret.trim()}>
            {t("signin.button")}
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <p className="muted">{t(mode === "oidc" ? "signin.memoryOidc" : "signin.memoryToken")}</p>
    </main>
  );
}
