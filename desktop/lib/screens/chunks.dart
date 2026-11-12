import 'package:flutter/material.dart';

import '../api/models.dart';
import '../i18n.dart';
import 'common.dart';

/// A list of chunks; tapping one shows it in the source panel.
class ChunkList extends StatelessWidget {
  const ChunkList({super.key, required this.chunks, required this.select, this.numbered = false});

  final List<Chunk> chunks;
  final void Function(Chunk) select;

  /// Prefix each chunk with its citation number "[n]".
  final bool numbered;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = I18n.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (var i = 0; i < chunks.length; i++)
        Card(
          margin: const EdgeInsets.symmetric(vertical: 4),
          child: InkWell(
            onTap: () => select(chunks[i]),
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${numbered ? '[${i + 1}] ' : ''}${chunkLabel(chunks[i], s)}',
                    style: theme.textTheme.bodySmall),
                if (chunks[i].symbol != null)
                  Text(chunks[i].symbol!,
                      style: const TextStyle(fontFamily: 'monospace', fontWeight: FontWeight.w600)),
                Text(chunks[i].text.split('\n').take(3).join('\n'),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace')),
              ]),
            ),
          ),
        ),
    ]);
  }
}
