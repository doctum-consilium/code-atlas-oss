/// Interface text in English and French.
///
/// The language comes from `GET /v1/public-config` (`language`); before that answer (or when it
/// fails) the platform locale decides. Every visible string goes through [Strings.t].
library;

import 'package:flutter/widgets.dart';

const supportedLanguages = {'en', 'fr'};

/// The language to use: the server's choice if supported, else the platform's, else English.
String pickLanguage(String? configured, String? platform) {
  if (configured != null && supportedLanguages.contains(configured)) return configured;
  if (platform != null && supportedLanguages.contains(platform)) return platform;
  return 'en';
}

const Map<String, Map<String, String>> dictionary = {
  'en': {
    'app.tagline': 'Find a notion in your repositories, and ask questions about them.',
    'boot.loading': 'Connecting to the code-atlas server…',
    'boot.failed': 'The code-atlas server at {url} cannot be reached: {error}',
    'boot.retry': 'Retry',
    'signin.oidc': 'Sign in with your identity provider',
    'signin.oidc.waiting': 'Signing in in the browser…',
    'signin.memory': 'Tokens stay in memory: closing the application forgets them.',
    'signin.token.missing':
        'No API token could be read from {path}. Paste the token printed by the server.',
    'signin.token.field': 'API token',
    'signin.token.submit': 'Sign in',
    'login.noBrowser': 'No browser could be opened on this machine.',
    'login.timeout': 'Sign-in timed out: try again.',
    'login.refused': 'Sign-in refused by the identity provider ({detail}).',
    'login.tokenRejected': 'The identity provider rejected the tokens ({detail}).',
    'login.noAccessToken': 'The identity provider answered without an access token.',
    'login.interrupted': 'Sign-in interrupted.',
    'login.tokenRequired': 'Paste an API token to sign in.',
    'login.page.success': 'Signed in',
    'login.page.close': 'You can close this tab and return to code-atlas.',
    'login.page.refused': 'Sign-in refused',
    'error.tooMany': 'Too many requests: try again in a minute.',
    'error.http': 'Error {status}',
    'tab.chat': 'Questions',
    'tab.search': 'Search',
    'tab.repos': 'Repositories',
    'action.signOut': 'Sign out',
    'history.new': 'New conversation',
    'filters.title': 'Filters',
    'filters.clear': 'clear',
    'filters.owners': 'Owner',
    'filters.types': 'Type',
    'filters.languages': 'Language',
    'filters.repos': 'Repository',
    'chat.empty': 'Ask a question about your code. The answer cites its sources in brackets.',
    'chat.hint': 'Your question…',
    'chat.ask': 'Ask',
    'chat.stop': 'Stop',
    'chat.local': 'on this machine',
    'chat.gateway': 'gateway, zero retention',
    'chat.invalidCitations': 'Citations without a matching source: {list}',
    'chat.sources': 'Sources ({count})',
    'chat.remoteBanner':
        'Code extracts are sent to {provider} (zero retention, checked on {date}).',
    'model.local': '{name} · local',
    'model.notInstalled': '{name} · local (not installed)',
    'model.gateway': '{alias} · {provider} zero retention',
    'search.hint': 'A notion, a function name, a rare word…',
    'search.hybrid': 'Words + meaning',
    'search.lexical': 'Exact words',
    'search.vector': 'Meaning only',
    'search.go': 'Search',
    'search.count': '{count} chunks in {ms} ms',
    'search.none': 'Nothing found: try other words, or remove filters.',
    'chunk.lines': '{location} · lines {start}–{end}',
    'chunk.cells': '{location} · cells {start}–{end}',
    'repos.loading': 'Loading…',
    'repos.summary': '{repos} repositories · {chunks} chunks',
    'repos.running': 'Update running: {message}',
    'repos.last': 'Last update: {message}',
    'repos.none': 'none since start-up',
    'repos.reindex': 'Update the index',
    'repos.col.repo': 'Repository',
    'repos.col.files': 'Files',
    'repos.col.chunks': 'Chunks',
    'repos.col.commit': 'Commit',
    'repos.localOnly': 'local only',
    'source.empty': 'Click a chunk or a citation to see the code.',
    'source.close': 'Close the source',
    'source.open': 'Open source',
    'source.wholeFile': 'Show whole file',
    'source.unavailable': 'File unavailable ({status})',
    'source.masked': 'Lines holding secrets are masked: {lines}',
  },
  'fr': {
    'app.tagline': 'Retrouver une notion dans vos dépôts, et poser des questions dessus.',
    'boot.loading': 'Connexion au serveur code-atlas…',
    'boot.failed': 'Le serveur code-atlas ({url}) est injoignable : {error}',
    'boot.retry': 'Réessayer',
    'signin.oidc': "Se connecter avec le fournisseur d'identité",
    'signin.oidc.waiting': 'Connexion dans le navigateur…',
    'signin.memory': "Les jetons restent en mémoire : fermer l'application les oublie.",
    'signin.token.missing':
        "Aucun jeton d'API n'a pu être lu dans {path}. Collez le jeton affiché par le serveur.",
    'signin.token.field': "Jeton d'API",
    'signin.token.submit': 'Se connecter',
    'login.noBrowser': "Aucun navigateur n'a pu être ouvert sur ce poste.",
    'login.timeout': 'Connexion expirée : réessayez.',
    'login.refused': "Connexion refusée par le fournisseur d'identité ({detail}).",
    'login.tokenRejected': "Le fournisseur d'identité a refusé les jetons ({detail}).",
    'login.noAccessToken': "Le fournisseur d'identité a répondu sans jeton d'accès.",
    'login.interrupted': 'Connexion interrompue.',
    'login.tokenRequired': "Collez un jeton d'API pour vous connecter.",
    'login.page.success': 'Connexion réussie',
    'login.page.close': 'Vous pouvez fermer cet onglet et revenir dans code-atlas.',
    'login.page.refused': 'Connexion refusée',
    'error.tooMany': 'Trop de requêtes : réessayez dans une minute.',
    'error.http': 'Erreur {status}',
    'tab.chat': 'Questions',
    'tab.search': 'Recherche',
    'tab.repos': 'Dépôts',
    'action.signOut': 'Se déconnecter',
    'history.new': 'Nouvelle conversation',
    'filters.title': 'Filtres',
    'filters.clear': 'effacer',
    'filters.owners': 'Propriétaire',
    'filters.types': 'Type',
    'filters.languages': 'Langage',
    'filters.repos': 'Dépôt',
    'chat.empty':
        'Posez une question sur votre code. La réponse cite ses sources entre crochets.',
    'chat.hint': 'Votre question…',
    'chat.ask': 'Demander',
    'chat.stop': 'Arrêter',
    'chat.local': 'sur le poste',
    'chat.gateway': 'passerelle, aucune conservation',
    'chat.invalidCitations': 'Citations sans source correspondante : {list}',
    'chat.sources': 'Sources ({count})',
    'chat.remoteBanner':
        'Les extraits de code partent vers {provider} (aucune conservation, vérifié le {date}).',
    'model.local': '{name} · poste',
    'model.notInstalled': '{name} · poste (non installé)',
    'model.gateway': '{alias} · {provider} sans conservation',
    'search.hint': 'Une notion, un nom de fonction, un mot rare…',
    'search.hybrid': 'Mots + sens',
    'search.lexical': 'Mots exacts',
    'search.vector': 'Sens seulement',
    'search.go': 'Chercher',
    'search.count': '{count} extraits en {ms} ms',
    'search.none': "Rien trouvé : essayez d'autres mots, ou retirez des filtres.",
    'chunk.lines': '{location} · lignes {start}–{end}',
    'chunk.cells': '{location} · cellules {start}–{end}',
    'repos.loading': 'Chargement…',
    'repos.summary': '{repos} dépôts · {chunks} extraits',
    'repos.running': 'Mise à jour en cours : {message}',
    'repos.last': 'Dernière mise à jour : {message}',
    'repos.none': 'aucune depuis le démarrage',
    'repos.reindex': "Mettre l'index à jour",
    'repos.col.repo': 'Dépôt',
    'repos.col.files': 'Fichiers',
    'repos.col.chunks': 'Extraits',
    'repos.col.commit': 'Commit',
    'repos.localOnly': 'local seulement',
    'source.empty': 'Cliquez sur un extrait ou une citation pour voir le code.',
    'source.close': 'Fermer la source',
    'source.open': 'Ouvrir la source',
    'source.wholeFile': 'Voir tout le fichier',
    'source.unavailable': 'Fichier indisponible ({status})',
    'source.masked': 'Lignes contenant des secrets masquées : {lines}',
  },
};

/// The strings of one language. A key missing in that language falls back to English, then to
/// the key itself (visible, so a missing translation is noticed rather than silently blank).
class Strings {
  const Strings(this.language);

  static const en = Strings('en');

  final String language;

  String t(String key, [Map<String, Object?> args = const {}]) {
    var text = dictionary[language]?[key] ?? dictionary['en']![key] ?? key;
    for (final MapEntry(:key, :value) in args.entries) {
      text = text.replaceAll('{$key}', '$value');
    }
    return text;
  }
}

/// Makes the [Strings] of the chosen language available to the widget tree.
class I18n extends InheritedWidget {
  const I18n({super.key, required this.strings, required super.child});

  final Strings strings;

  /// The strings in scope; English when no [I18n] is above [context] (isolated widget tests).
  static Strings of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<I18n>()?.strings ?? Strings.en;

  @override
  bool updateShouldNotify(I18n oldWidget) => oldWidget.strings.language != strings.language;
}
