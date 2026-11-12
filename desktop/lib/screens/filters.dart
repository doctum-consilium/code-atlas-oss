import 'package:flutter/material.dart';

import '../api/models.dart';
import '../i18n.dart';

class FiltersPanel extends StatelessWidget {
  const FiltersPanel({super.key, required this.facets, required this.filters, required this.onChanged});
  final Facets facets;
  final Filters filters;
  final void Function(Filters) onChanged;

  @override
  Widget build(BuildContext context) {
    final s = I18n.of(context);
    final groups = <(String, List<String>, Set<String>)>[
      ('owners', facets.owners, filters.owners),
      ('types', facets.types, filters.types),
      ('languages', facets.languages, filters.languages),
      ('repos', facets.repos, filters.repos),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Text('${s.t('filters.title')}${filters.count > 0 ? ' (${filters.count})' : ''}',
            style: Theme.of(context).textTheme.titleSmall),
        if (filters.count > 0)
          TextButton(onPressed: () => onChanged(const Filters()), child: Text(s.t('filters.clear'))),
      ]),
      for (final (group, values, active) in groups)
        ExpansionTile(
          title: Text(s.t('filters.$group')),
          initiallyExpanded: group != 'repos',
          tilePadding: EdgeInsets.zero,
          children: [
            for (final v in values)
              CheckboxListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: Text(v, style: const TextStyle(fontSize: 13)),
                value: active.contains(v),
                onChanged: (_) => onChanged(filters.toggle(group, v)),
              ),
          ],
        ),
    ]);
  }
}
