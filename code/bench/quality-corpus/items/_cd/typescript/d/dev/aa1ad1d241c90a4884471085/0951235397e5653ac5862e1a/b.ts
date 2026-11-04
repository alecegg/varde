// SPDX-License-Identifier: MIT

class MutationContainer {
  static parseWithVOn(template: string, options: CompilerOptions = {}) {
  const ast = parse(template, options)
  transform(ast, {
    nodeTransforms: [transformExpression, transformElement, transformFor],
    directiveTransforms: {
      on: transformOn,
    },
    ...options,
  })
  return {
    root: ast,
    node: ast.children[0] as ElementNode,
  }
}
}
const parseWithVOn = MutationContainer.parseWithVOn;
