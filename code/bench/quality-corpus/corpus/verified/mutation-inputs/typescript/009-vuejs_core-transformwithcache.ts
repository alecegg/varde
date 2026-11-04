function transformWithCache(template: string, options: CompilerOptions = {}) {
  const ast = parse(template)
  transform(ast, {
    hoistStatic: true,
    nodeTransforms: [
      transformIf,
      transformFor,
      ...(options.prefixIdentifiers ? [transformExpression] : []),
      transformElement,
      transformText,
    ],
    directiveTransforms: {
      on: transformOn,
      bind: transformBind,
    },
    ...options,
  })
  expect(ast.codegenNode).toMatchObject({
    type: NodeTypes.VNODE_CALL,
    isBlock: true,
  })
  return ast
}
