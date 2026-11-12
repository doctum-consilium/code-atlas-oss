/// Events of the answer stream (`POST /v1/chat`, `text/event-stream`).
///
/// OpenAPI cannot describe a server-sent event stream, so these payloads follow the backend
/// (`atlas/server.py`, `_stream`): `chunks`, then `token`s, then `done` — or `error`. The chunks
/// carried by `chunks` are `ChunkOut` objects, checked by the contract test through [Chunk].
library;

import 'dart:convert';

import 'models.dart';

/// One raw event: its name and its decoded JSON data.
class SseEvent {
  const SseEvent(this.name, this.data);
  final String name;
  final Json data;
}

/// Splits an SSE buffer; returns the complete events and the unfinished rest.
({List<SseEvent> events, String rest}) parseSse(String buffer) {
  final blocks = buffer.split('\n\n');
  final rest = blocks.removeLast();
  final events = <SseEvent>[];
  for (final block in blocks) {
    var name = 'message';
    final data = <String>[];
    for (final line in block.split('\n')) {
      if (line.startsWith('event:')) name = line.substring(6).trim();
      if (line.startsWith('data:')) data.add(line.substring(5).trim());
    }
    if (data.isEmpty) continue;
    try {
      final decoded = jsonDecode(data.join('\n'));
      if (decoded is Json) events.add(SseEvent(name, decoded));
    } on FormatException {
      continue;
    }
  }
  return (events: events, rest: rest);
}

sealed class ChatEvent {
  const ChatEvent();

  /// The typed event, or `null` for an event name this version does not know (ignored).
  static ChatEvent? from(SseEvent e) => switch (e.name) {
        'chunks' => ChunksEvent(
            conversationId: e.data['conversation_id'] as String,
            model: e.data['model'] as String,
            provider: e.data['provider'] as String,
            remote: e.data['remote'] as bool,
            chunks: (e.data['chunks'] as List<dynamic>)
                .map((c) => Chunk.fromJson(c as Json))
                .toList(),
          ),
        'token' => TokenEvent(e.data['text'] as String),
        'done' => DoneEvent(
            conversationId: e.data['conversation_id'] as String,
            invalidCitations: (e.data['invalid_citations'] as List<dynamic>).cast<int>(),
          ),
        'error' => ErrorEvent(e.data['reason'] as String),
        _ => null,
      };
}

/// The chunks given to the model, and where the question goes.
class ChunksEvent extends ChatEvent {
  const ChunksEvent({
    required this.conversationId,
    required this.model,
    required this.provider,
    required this.remote,
    required this.chunks,
  });
  final String conversationId, model, provider;
  final bool remote;
  final List<Chunk> chunks;
}

/// A piece of the answer.
class TokenEvent extends ChatEvent {
  const TokenEvent(this.text);
  final String text;
}

/// The answer is complete; [invalidCitations] are numbers that match no chunk.
class DoneEvent extends ChatEvent {
  const DoneEvent({required this.conversationId, required this.invalidCitations});
  final String conversationId;
  final List<int> invalidCitations;
}

/// The model failed or was refused mid-way.
class ErrorEvent extends ChatEvent {
  const ErrorEvent(this.reason);
  final String reason;
}
