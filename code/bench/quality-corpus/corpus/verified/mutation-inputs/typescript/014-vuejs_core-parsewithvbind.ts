function parseWithVBind(
  template: string,
  options: CompilerOptions = {},
): ElementNode {
  const ast = parse(template)
  transform(ast, {
    nodeTransforms: [
      transformVBindShorthand,
      ...(options.prefixIdentifiers ? [transformExpression] : []),
      transformElement,
    ],
    directiveTransforms: {
      bind: transformBind,
    },
    ...options,
  })
  return ast.children[0] as ElementNode
}
