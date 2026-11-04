function transformWithTextOpt(template: string, options: CompilerOptions = {}) {
  const ast = parse(template)
  transform(ast, {
    nodeTransforms: [
      transformFor,
      ...(options.prefixIdentifiers ? [transformExpression] : []),
      transformElement,
      transformText,
    ],
    ...options,
  })
  return ast
}
