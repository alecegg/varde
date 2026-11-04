function addMapping(loc: Position, name: string | null = null) {
  // we use the private property to directly add the mapping
  // because the addMapping() implementation in source-map-js has a bunch of
  // unnecessary arg and validation checks that are pure overhead in our case.
  const { _names, _mappings } = context.map!
  if (name !== null && !_names.has(name)) _names.add(name)
  _mappings.add({
    originalLine: loc.line,
    originalColumn: loc.column - 1, // source-map column is 0 based
    generatedLine: context.line,
    generatedColumn: context.column - 1,
    source: filename,
    name,
  })
}
