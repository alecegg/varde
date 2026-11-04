function parseWithSlots(
  template: string,
  options: CompilerOptions & { transformText?: boolean } = {},
) {
  const ast = parse(template, {
    whitespace: options.whitespace,
  })
  transform(ast, {
    nodeTransforms: [
      transformIf,
      transformFor,
      ...(options.prefixIdentifiers
        ? [trackVForSlotScopes, transformExpression]
        : []),
      transformSlotOutlet,
      transformElement,
      trackSlotScopes,
      ...(options.transformText ? [transformText] : []),
    ],
    directiveTransforms: {
      on: transformOn,
      bind: transformBind,
    },
    ...options,
  })
  return {
    root: ast,
    slots:
      ast.children[0].type === NodeTypes.ELEMENT
        ? ((ast.children[0].codegenNode as VNodeCall)
            .children as SlotsExpression)
        : null,
  }
}
