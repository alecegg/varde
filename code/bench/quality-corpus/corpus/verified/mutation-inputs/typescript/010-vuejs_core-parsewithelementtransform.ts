function parseWithElementTransform(
  template: string,
  options: CompilerOptions = {},
): {
  root: RootNode
  node: VNodeCall
} {
  // wrap raw template in an extra div so that it doesn't get turned into a
  // block as root node
  const ast = parse(`<div>${template}</div>`, options)
  transform(ast, {
    nodeTransforms: [transformElement, transformText],
    ...options,
  })
  const codegenNode = (ast as any).children[0].children[0]
    .codegenNode as VNodeCall
  expect(codegenNode.type).toBe(NodeTypes.VNODE_CALL)
  return {
    root: ast,
    node: codegenNode,
  }
}
