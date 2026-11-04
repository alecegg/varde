export function parseWithForTransform(
  template: string,
  options: CompilerOptions = {},
): {
  root: RootNode
  node: ForNode & { codegenNode: ForCodegenNode }
} {
  const ast = parse(template, options)
  transform(ast, {
    nodeTransforms: [
      transformVBindShorthand,
      transformIf,
      transformFor,
      ...(options.prefixIdentifiers ? [transformExpression] : []),
      transformSlotOutlet,
      transformElement,
    ],
    directiveTransforms: {
      bind: transformBind,
    },
    ...options,
  })
  return {
    root: ast,
    node: ast.children[0] as ForNode & { codegenNode: ForCodegenNode },
  }
}
