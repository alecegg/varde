function parseWithIfTransform(
  template: string,
  options: CompilerOptions = {},
  returnIndex: number = 0,
  childrenLen: number = 1,
) {
  const ast = parse(template, options)
  transform(ast, {
    nodeTransforms: [
      transformVBindShorthand,
      transformIf,
      transformSlotOutlet,
      transformElement,
    ],
    ...options,
  })
  if (!options.onError) {
    expect(ast.children.length).toBe(childrenLen)
    for (let i = 0; i < childrenLen; i++) {
      expect(ast.children[i].type).toBe(NodeTypes.IF)
    }
  }
  return {
    root: ast,
    node: ast.children[returnIndex] as IfNode & {
      codegenNode: IfConditionalExpression
    },
  }
}
