function parseWithSlots(template: string, options: CompilerOptions = {}) {
  const ast = parse(template)
  transform(ast, {
    nodeTransforms: [
      ...(options.prefixIdentifiers ? [transformExpression] : []),
      transformSlotOutlet,
      transformElement,
    ],
    directiveTransforms: {
      on: transformOn,
      bind: transformBind,
    },
    ...options,
  })
  return ast
}
