import 'package:flutter/material.dart';

import '../auth/session.dart';
import '../i18n.dart';
import 'common.dart';

class _Frame extends StatelessWidget {
  const _Frame({required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text('code-atlas', style: Theme.of(context).textTheme.headlineMedium),
              const SizedBox(height: 8),
              Text(I18n.of(context).t('app.tagline'), textAlign: TextAlign.center),
              const SizedBox(height: 24),
              ...children,
              const SizedBox(height: 16),
              Text(I18n.of(context).t('signin.memory'),
                  style: Theme.of(context).textTheme.bodySmall),
            ]),
          ),
        ),
      );
}

/// OIDC mode: sign-in in the system browser.
class OidcSignInScreen extends StatefulWidget {
  const OidcSignInScreen({super.key, required this.session});
  final Session session;
  @override
  State<OidcSignInScreen> createState() => _OidcSignInScreenState();
}

class _OidcSignInScreenState extends State<OidcSignInScreen> {
  Object? _error;
  bool _running = false;

  Future<void> _signIn() async {
    setState(() {
      _running = true;
      _error = null;
    });
    try {
      await widget.session.login();
    } on Exception catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = I18n.of(context);
    return _Frame(children: [
      FilledButton(
        onPressed: _running ? null : _signIn,
        child: Text(s.t(_running ? 'signin.oidc.waiting' : 'signin.oidc')),
      ),
      if (_error != null) ...[
        const SizedBox(height: 12),
        Text(describeError(_error!, s), style: TextStyle(color: Theme.of(context).colorScheme.error)),
      ],
    ]);
  }
}

/// Token mode, when the token file could not be read: paste the token (kept in memory only).
class TokenSignInScreen extends StatefulWidget {
  const TokenSignInScreen({super.key, required this.session, required this.tokenPath});
  final Session session;
  final String? tokenPath;
  @override
  State<TokenSignInScreen> createState() => _TokenSignInScreenState();
}

class _TokenSignInScreenState extends State<TokenSignInScreen> {
  final _input = TextEditingController();
  Object? _error;

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  void _submit() {
    try {
      widget.session.useToken(_input.text);
    } on Exception catch (e) {
      setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = I18n.of(context);
    return _Frame(children: [
      Text(s.t('signin.token.missing', {'path': widget.tokenPath ?? '~/.config/code-atlas/api-token'}),
          textAlign: TextAlign.center),
      const SizedBox(height: 12),
      TextField(
        key: const Key('token'),
        controller: _input,
        obscureText: true,
        autocorrect: false,
        enableSuggestions: false,
        decoration: InputDecoration(labelText: s.t('signin.token.field'), border: const OutlineInputBorder()),
        onSubmitted: (_) => _submit(),
      ),
      const SizedBox(height: 12),
      FilledButton(onPressed: _submit, child: Text(s.t('signin.token.submit'))),
      if (_error != null) ...[
        const SizedBox(height: 12),
        Text(describeError(_error!, s), style: TextStyle(color: Theme.of(context).colorScheme.error)),
      ],
    ]);
  }
}
