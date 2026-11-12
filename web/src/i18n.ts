/**
 * User interface text in English and French.
 *
 * The language comes from GET /v1/public-config (``language``); before that answer, and if it never
 * comes, the browser language decides. Every visible string goes through ``t``. This module has no
 * React dependency so that the popup callback page and the end-to-end test can use it too; the React
 * hook lives in ``useLanguage.ts``.
 */

const en = {
  "app.title": "code-atlas",
  "app.tagline": "Find a concept in your repositories, and ask questions about it.",

  "boot.loading": "Loading…",
  "boot.failed": "Cannot start: the API at {url} is unreachable or misconfigured.",

  "signin.button": "Sign in",
  "signin.tokenLabel": "API token",
  "signin.tokenHelp":
    "The token is in ~/.config/code-atlas/api-token on this machine, created by the `atlas token` command.",
  "signin.cancelled": "Sign-in cancelled or refused.",
  "signin.memoryOidc": "Tokens stay in memory: reloading the page asks you to sign in again.",
  "signin.memoryToken": "The token stays in memory only: reloading the page asks for it again.",

  "nav.label": "Modes",
  "nav.ask": "Questions",
  "nav.search": "Search",
  "nav.repos": "Repositories",
  "header.signOut": "Sign out",

  "history.label": "History",
  "history.new": "New conversation",

  "filters.label": "Filters",
  "filters.clear": "clear",
  "filters.owners": "Owner",
  "filters.types": "Type",
  "filters.languages": "Language",
  "filters.repos": "Repository",

  "chunk.lines": "lines",
  "chunk.cells": "cells",
  "chunk.location": "{repo}/{path} · {unit} {start}–{end}",

  "search.label": "Search",
  "search.input": "What you are looking for",
  "search.placeholder": "A concept, a function name, a rare word…",
  "search.mode": "How to search",
  "search.hybrid": "Words + meaning",
  "search.lexical": "Exact words",
  "search.vector": "Meaning only",
  "search.submit": "Find",
  "search.running": "Searching…",
  "search.count.one": "{n} result in {ms} ms",
  "search.count.other": "{n} results in {ms} ms",
  "search.none": "Nothing found: try other words, or remove some filters.",

  "source.label": "Source",
  "source.empty": "Click a result or a citation to see the code.",
  "source.close": "Close source",
  "source.open": "Open source",
  "source.wholeFile": "View whole file",
  "source.unavailable": "File unavailable ({status})",

  "model.label": "Model",
  "model.local": "On this machine (nothing leaves)",
  "model.notInstalled": "{name} (not installed)",
  "model.gateway": "Gateway — zero data retention (ZDR)",
  "model.remoteBanner": "Code extracts are sent to {provider} (zero retention, checked on {date}).",

  "chat.label": "Questions",
  "chat.intro":
    "Ask a question about your code, for instance “where do I check that a user may export a report?”. The answer cites its sources in brackets.",
  "chat.gateway": "{model} · ZDR gateway",
  "chat.local": "{model} · on this machine",
  "chat.invalid": "Citations without a matching chunk: {list}",
  "chat.sources": "Sources ({n})",
  "chat.input": "Your question",
  "chat.placeholder": "Your question…",
  "chat.ask": "Ask",
  "chat.stop": "Stop",
  "chat.unknownError": "Unknown error",

  "repos.label": "Indexed repositories",
  "repos.loading": "Loading…",
  "repos.summary.one": "{n} repository · {chunks} chunks",
  "repos.summary.other": "{n} repositories · {chunks} chunks",
  "repos.running": "Update in progress: {message}",
  "repos.last": "Last update: {message}",
  "repos.never": "none since start-up",
  "repos.update": "Update the index",
  "repos.col.repo": "Repository",
  "repos.col.files": "Files",
  "repos.col.chunks": "Chunks",
  "repos.col.commit": "Commit",
  "repos.col.indexed": "Indexed on",
  "repos.local": "local",
  "repos.localTitle": "never leaves this machine",

  "error.tooMany": "Too many requests: try again in a minute.",
  "error.status": "Error {status}",
  "error.unreachable": "API unreachable",

  "callback.pending": "Signing in…",
  "callback.failed": "Sign-in interrupted: close this window and try again.",
} satisfies Record<string, string>;

export type Key = keyof typeof en;

const fr: Record<Key, string> = {
  "app.title": "code-atlas",
  "app.tagline": "Retrouve une notion dans tes dépôts, et pose des questions dessus.",

  "boot.loading": "Chargement…",
  "boot.failed": "Démarrage impossible : l'API ({url}) est injoignable ou mal configurée.",

  "signin.button": "Se connecter",
  "signin.tokenLabel": "Jeton d'API",
  "signin.tokenHelp":
    "Le jeton se trouve dans ~/.config/code-atlas/api-token sur ce poste ; la commande `atlas token` le crée.",
  "signin.cancelled": "Connexion annulée ou refusée.",
  "signin.memoryOidc": "Les jetons restent en mémoire : recharger la page demande une reconnexion.",
  "signin.memoryToken": "Le jeton reste en mémoire seulement : recharger la page le redemande.",

  "nav.label": "Modes",
  "nav.ask": "Questions",
  "nav.search": "Recherche",
  "nav.repos": "Dépôts",
  "header.signOut": "Se déconnecter",

  "history.label": "Historique",
  "history.new": "Nouvelle conversation",

  "filters.label": "Filtres",
  "filters.clear": "effacer",
  "filters.owners": "Propriétaire",
  "filters.types": "Type",
  "filters.languages": "Langage",
  "filters.repos": "Dépôt",

  "chunk.lines": "lignes",
  "chunk.cells": "cellules",
  "chunk.location": "{repo}/{path} · {unit} {start}–{end}",

  "search.label": "Recherche",
  "search.input": "Ce que tu cherches",
  "search.placeholder": "Une notion, un nom de fonction, un mot rare…",
  "search.mode": "Façon de chercher",
  "search.hybrid": "Mots + sens",
  "search.lexical": "Mots exacts",
  "search.vector": "Sens seulement",
  "search.submit": "Chercher",
  "search.running": "Recherche…",
  "search.count.one": "{n} passage en {ms} ms",
  "search.count.other": "{n} passages en {ms} ms",
  "search.none": "Rien trouvé : essaie d'autres mots, ou retire des filtres.",

  "source.label": "Source",
  "source.empty": "Clique sur un passage ou une citation pour voir le code.",
  "source.close": "Fermer la source",
  "source.open": "Ouvrir la source",
  "source.wholeFile": "Voir tout le fichier",
  "source.unavailable": "Fichier indisponible ({status})",

  "model.label": "Modèle",
  "model.local": "Sur le poste (rien ne sort)",
  "model.notInstalled": "{name} (non installé)",
  "model.gateway": "Passerelle — zéro conservation (ZDR)",
  "model.remoteBanner": "Les extraits de code partent vers {provider} (zéro conservation, vérifié le {date}).",

  "chat.label": "Questions",
  "chat.intro":
    "Pose une question sur ton code, par exemple « où est-ce que je vérifie qu'un utilisateur peut exporter un rapport ? ». La réponse cite ses sources entre crochets.",
  "chat.gateway": "{model} · passerelle ZDR",
  "chat.local": "{model} · sur le poste",
  "chat.invalid": "Citations sans passage correspondant : {list}",
  "chat.sources": "Sources ({n})",
  "chat.input": "Ta question",
  "chat.placeholder": "Ta question…",
  "chat.ask": "Demander",
  "chat.stop": "Arrêter",
  "chat.unknownError": "Erreur inconnue",

  "repos.label": "Dépôts indexés",
  "repos.loading": "Chargement…",
  "repos.summary.one": "{n} dépôt · {chunks} passages",
  "repos.summary.other": "{n} dépôts · {chunks} passages",
  "repos.running": "Mise à jour en cours : {message}",
  "repos.last": "Dernière mise à jour : {message}",
  "repos.never": "aucune depuis le démarrage",
  "repos.update": "Mettre l'index à jour",
  "repos.col.repo": "Dépôt",
  "repos.col.files": "Fichiers",
  "repos.col.chunks": "Passages",
  "repos.col.commit": "Commit",
  "repos.col.indexed": "Indexé le",
  "repos.local": "local",
  "repos.localTitle": "ne quitte jamais le poste",

  "error.tooMany": "Trop de requêtes : réessaie dans une minute.",
  "error.status": "Erreur {status}",
  "error.unreachable": "API injoignable",

  "callback.pending": "Connexion en cours…",
  "callback.failed": "Connexion interrompue : ferme cette fenêtre et réessaie.",
};

export type Language = "en" | "fr";

export const dictionaries: Record<Language, Record<Key, string>> = { en, fr };

type Params = Record<string, string | number>;

/** Keys that exist in a ``.one`` and an ``.other`` form. */
export type PluralKey = { [K in Key]: K extends `${infer Base}.one` ? Base : never }[Key];

/** Browser language tag (``fr-FR``, ``en``…) to a supported language; English otherwise. */
export function detectLanguage(tag: string | undefined): Language {
  return tag?.toLowerCase().startsWith("fr") ? "fr" : "en";
}

let current: Language = detectLanguage(typeof navigator === "undefined" ? undefined : navigator.language);
const listeners = new Set<() => void>();

export function getLanguage(): Language {
  return current;
}

export function setLanguage(language: Language): void {
  if (language === current) return;
  current = language;
  if (typeof document !== "undefined") document.documentElement.lang = language;
  for (const listener of listeners) listener();
}

export function subscribeLanguage(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Text of ``key`` in ``language``, with ``{name}`` placeholders filled from ``params``. */
export function translate(language: Language, key: Key, params?: Params): string {
  const text = dictionaries[language][key];
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) => (name in params ? String(params[name]) : whole));
}

/** Text of ``key`` in the current language. */
export function t(key: Key, params?: Params): string {
  return translate(current, key, params);
}

/** Singular or plural form of ``key`` for the count ``n`` (French treats 0 and 1 as singular). */
export function tn(key: PluralKey, n: number, params: Params = {}): string {
  const one = current === "fr" ? n < 2 : n === 1;
  return t(`${key}.${one ? "one" : "other"}`, { n, ...params });
}
