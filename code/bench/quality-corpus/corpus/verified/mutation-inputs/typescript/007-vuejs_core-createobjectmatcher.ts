export function createObjectMatcher(obj: Record<string, any>): {
  type: NodeTypes
  properties: Partial<Property>[]
} {
  return {
    type: NodeTypes.JS_OBJECT_EXPRESSION,
    properties: Object.keys(obj).map(key => ({
      type: NodeTypes.JS_PROPERTY,
      key: {
        type: NodeTypes.SIMPLE_EXPRESSION,
        content: key.replace(bracketsRE, ''),
        isStatic: !leadingBracketRE.test(key),
      } as SimpleExpressionNode,
      value: isString(obj[key])
        ? {
            type: NodeTypes.SIMPLE_EXPRESSION,
            content: obj[key].replace(bracketsRE, ''),
            isStatic: !leadingBracketRE.test(obj[key]),
          }
        : obj[key],
    })),
  }
}
