/**
 * Popup callback page (signin.html): hands the authorization answer back to the main window, which
 * holds the PKCE state in memory and does the token exchange, then closes. The settings below are
 * placeholders (the callback does not use them); memory stores keep this page away from
 * sessionStorage as well.
 */
import { InMemoryWebStorage, UserManager, WebStorageStateStore } from "oidc-client-ts";

import { t } from "./i18n";

document.body.textContent = t("callback.pending");
const memory = new InMemoryWebStorage();
void new UserManager({
  authority: window.location.origin,
  client_id: "popup-callback",
  redirect_uri: "",
  userStore: new WebStorageStateStore({ store: memory }),
  stateStore: new WebStorageStateStore({ store: memory }),
})
  .signinPopupCallback()
  .catch(() => {
    document.body.textContent = t("callback.failed");
  });
