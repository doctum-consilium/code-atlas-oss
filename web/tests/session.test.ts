import type { User, UserManager } from "oidc-client-ts";
import { describe, expect, it, vi } from "vitest";

import { createSession, OidcSession, oidcSettings, TokenSession } from "../src/auth";
import { browserStorageSize } from "./helpers";

const OIDC = { issuer: "https://sso.example.org/realms/dev", web_client: "code-atlas-web", desktop_client: "d" };

function fakeUser(token: string, expired = false): User {
  return { access_token: token, id_token: "id-" + token, expired } as unknown as User;
}

function fakeManager() {
  const handlers: Record<string, ((u?: User) => void)[]> = { loaded: [], renewError: [], expired: [] };
  const manager = {
    events: {
      addUserLoaded: (h: (u?: User) => void) => handlers.loaded?.push(h),
      addSilentRenewError: (h: () => void) => handlers.renewError?.push(h),
      addAccessTokenExpired: (h: () => void) => handlers.expired?.push(h),
    },
    signinPopup: vi.fn((args: { prompt?: string }) => Promise.resolve(fakeUser(args.prompt ? "fresh" : "first"))),
    removeUser: vi.fn(() => Promise.resolve()),
    signoutRedirect: vi.fn(() => Promise.resolve()),
  };
  const fire = (name: string, u?: User) => {
    for (const h of handlers[name] ?? []) h(u);
  };
  return { manager, fire, asManager: manager as unknown as UserManager };
}

describe("TokenSession", () => {
  it("keeps the token in memory, notifies, and forgets it", async () => {
    const session = new TokenSession();
    const seen: boolean[] = [];
    const stop = session.subscribe((c) => seen.push(c));
    expect(session.connected).toBe(false);
    await session.signIn("  secret-value  ");
    expect(session.token()).toBe("secret-value");
    await session.reauthenticate();
    expect(session.connected).toBe(true);
    session.forget();
    expect(session.token()).toBeNull();
    await session.signIn("again");
    await session.signOut();
    expect(session.connected).toBe(false);
    stop();
    expect(seen).toEqual([true, false, true, false]);
    expect(browserStorageSize()).toBe(0);
  });
  it("refuses an empty token", async () => {
    await expect(new TokenSession().signIn("   ")).rejects.toThrow("empty token");
  });
});

describe("OidcSession", () => {
  it("signs in through a popup, re-authenticates with prompt=login, and signs out", async () => {
    const { manager, asManager } = fakeManager();
    const session = new OidcSession(OIDC, asManager);
    expect(session.token()).toBeNull();
    await session.signIn();
    expect(manager.signinPopup).toHaveBeenLastCalledWith({});
    expect(session.token()).toBe("first");
    await session.reauthenticate();
    expect(manager.signinPopup).toHaveBeenLastCalledWith({ prompt: "login" });
    expect(session.token()).toBe("fresh");
    await session.signOut();
    expect(session.connected).toBe(false);
    expect(manager.removeUser).toHaveBeenCalled();
    expect(manager.signoutRedirect).toHaveBeenCalledWith({ id_token_hint: "id-fresh" });
    await session.signOut();
    expect(manager.signoutRedirect).toHaveBeenLastCalledWith({});
  });
  it("follows the events of the OIDC client", () => {
    const { fire, asManager } = fakeManager();
    const session = new OidcSession(OIDC, asManager);
    const listener = vi.fn();
    session.subscribe(listener);
    fire("loaded", fakeUser("renewed"));
    expect(session.token()).toBe("renewed");
    fire("renewError");
    expect(session.connected).toBe(false);
    fire("loaded", fakeUser("x"));
    fire("expired");
    expect(session.connected).toBe(false);
    fire("loaded", fakeUser("old", true));
    expect(session.token()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(5);
  });
  it("keeps users and PKCE state in memory, and returns to signin.html", () => {
    const settings = oidcSettings(OIDC, "http://localhost:5173");
    expect(settings.authority).toBe(OIDC.issuer);
    expect(settings.client_id).toBe("code-atlas-web");
    expect(settings.popup_redirect_uri).toBe("http://localhost:5173/signin.html");
    expect(settings.automaticSilentRenew).toBe(true);
    expect(settings.userStore).toBeDefined();
    expect(settings.stateStore).toBeDefined();
  });
});

describe("createSession", () => {
  it("picks the session that matches the sign-in mode", () => {
    expect(createSession({ auth_mode: "token", language: "en" })).toBeInstanceOf(TokenSession);
    expect(createSession({ auth_mode: "oidc", language: "en", oidc: OIDC })).toBeInstanceOf(OidcSession);
    expect(() => createSession({ auth_mode: "oidc", language: "en", oidc: null })).toThrow(/oidc settings/);
  });
});
