function transformWithCodegen(template: string) {
  const ast = baseParse(template)
  transform(ast, {
    nodeTransforms: [
      transformIf,
      transformFor,
      transformText,
      transformSlotOutlet,
      transformElement,
    ],
  })
  return ast
}
