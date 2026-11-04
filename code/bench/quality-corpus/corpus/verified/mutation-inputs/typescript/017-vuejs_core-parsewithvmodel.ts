function parseWithVModel(template: string, options: CompilerOptions = {}) {
  const ast = parse(template)

  transform(ast, {
    nodeTransforms: [
      transformFor,
      transformExpression,
      transformElement,
      trackSlotScopes,
    ],
    directiveTransforms: {
      ...options.directiveTransforms,
      model: transformModel,
    },
    ...options,
  })

  return ast
}
