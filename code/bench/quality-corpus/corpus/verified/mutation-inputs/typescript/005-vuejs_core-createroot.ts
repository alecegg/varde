function createRoot(options: Partial<RootNode> = {}): RootNode {
  return {
    type: NodeTypes.ROOT,
    source: '',
    children: [],
    helpers: new Set(),
    components: [],
    directives: [],
    imports: [],
    hoists: [],
    cached: [],
    temps: 0,
    codegenNode: createSimpleExpression(`null`, false),
    loc: locStub,
    ...options,
  }
}
