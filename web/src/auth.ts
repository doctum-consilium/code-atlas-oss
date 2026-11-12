/**
 * Sign-in sessions. The backend runs in one of two modes, announced by GET /v1/public-config:
 *
 * - ``oidc``: authorization code + PKCE with a public client (OidcSession);
 * - ``token``: a local API token pasted on the sign-in screen (TokenSession).
 *
 * In both modes the credentials live in memory only: no localStorage, no sessionStorage, no cookie.
 * Reloading the page therefore asks to sign in again.
 */
import {
  InMemoryWebStorage,
  UserManager,
  WebStorageStateStore,
  type User,
  type UserManagerSettings,
} from "oidc-client-ts";

import type { PublicConfig } from "./config";

export type Listener = (connected: boolean) => void;
export type AuthMode = PublicConfig["auth_mode"];

export interface Session {
  readonly mode: AuthMode;
  readonly connected: boolean;
  /** Current bearer token, or null. Never logged. */
  token(): string | null;
  /** Signs in; ``secret`` is the API token in token mode and is ignored in OIDC mode. */
  signIn(secret?: string): Promise<void>;
  signOut(): Promise<void>;
  /** The API answered 401: drop the credentials so that the screen asks again. */
  forget(): void;
  /** Fresh sign-in before an admin action (403 on POST /v1/index). */
  reauthenticate(): Promise<void>;
  subscribe(listener: Listener): () => void;
}

abstract class BaseSession {
  private readonly listeners = new Set<Listener>();

  abstract get connected(): boolean;

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  protected notify(): void {
    for (const listener of this.listeners) listener(this.connected);
  }
}

/** Local API token, kept in memory only and sent as a bearer token. */
export class TokenSession extends BaseSession implements Session {
  readonly mode = "token" as const;
  private secret: string | null = null;

  get connected(): boolean {
    return this.secret !== null;
  }

  token(): string | null {
    return this.secret;
  }

  signIn(secret?: string): Promise<void> {
    const value = secret?.trim();
    if (!value) return Promise.reject(new Error("empty token"));
    this.secret = value;
    this.notify();
    return Promise.resolve();
  }

  signOut(): Promise<void> {
    this.forget();
    return Promise.resolve();
  }

  forget(): void {
    this.secret = null;
    this.notify();
  }

  /** The token is all there is: nothing fresher to obtain. */
  reauthenticate(): Promise<void> {
    return Promise.resolve();
  }
}

export type OidcPublic = NonNullable<PublicConfig["oidc"]>;

/**
 * Settings of the OIDC client. Sign-in goes through a popup, so the page does not reload and the
 * PKCE state can stay in memory too; the access token is renewed with the refresh token before it
 * expires.
 */
export function oidcSettings(oidc: Pick<OidcPublic, "issuer" | "web_client">, origin: string): UserManagerSettings {
  const memory = new InMemoryWebStorage();
  return {
    authority: oidc.issuer,
    client_id: oidc.web_client,
    redirect_uri: `${origin}/signin.html`,
    popup_redirect_uri: `${origin}/signin.html`,
    post_logout_redirect_uri: origin,
    response_type: "code",
    scope: "openid email profile",
    userStore: new WebStorageStateStore({ store: memory }),
    stateStore: new WebStorageStateStore({ store: memory }),
    automaticSilentRenew: true,
    monitorSession: false,
    loadUserInfo: false,
  };
}

export class OidcSession extends BaseSession implements Session {
  readonly mode = "oidc" as const;
  private readonly manager: UserManager;
  private user: User | null = null;

  constructor(oidc: Pick<OidcPublic, "issuer" | "web_client">, manager?: UserManager) {
    super();
    this.manager = manager ?? new UserManager(oidcSettings(oidc, window.location.origin));
    this.manager.events.addUserLoaded((u) => {
      this.user = u;
      this.notify();
    });
    this.manager.events.addSilentRenewError(() => {
      this.forget();
    });
    this.manager.events.addAccessTokenExpired(() => {
      this.forget();
    });
  }

  get connected(): boolean {
    return this.user !== null && !this.user.expired;
  }

  token(): string | null {
    return this.connected ? (this.user?.access_token ?? null) : null;
  }

  async signIn(): Promise<void> {
    await this.popup(false);
  }

  /** Admin actions need a recent login: the issuer is asked to prompt again. */
  async reauthenticate(): Promise<void> {
    await this.popup(true);
  }

  async signOut(): Promise<void> {
    const idToken = this.user?.id_token;
    this.forget();
    await this.manager.removeUser();
    await this.manager.signoutRedirect(idToken ? { id_token_hint: idToken } : {});
  }

  forget(): void {
    this.user = null;
    this.notify();
  }

  private async popup(forceLogin: boolean): Promise<void> {
    this.user = await this.manager.signinPopup(forceLogin ? { prompt: "login" } : {});
    this.notify();
  }
}

export function createSession(publicConfig: PublicConfig): Session {
  if (publicConfig.auth_mode === "oidc") {
    if (!publicConfig.oidc) throw new Error("auth_mode is oidc but the oidc settings are missing");
    return new OidcSession(publicConfig.oidc);
  }
  return new TokenSession();
}
