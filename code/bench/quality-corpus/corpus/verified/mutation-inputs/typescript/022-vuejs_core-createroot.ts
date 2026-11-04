export function createRoot(
  children: TemplateChildNode[],
  source = '',
): RootNode {
  return {
    type: NodeTypes.ROOT,
    source,
    children,
    helpers: new Set(),
    components: [],
    directives: [],
    hoists: [],
    imports: [],
    cached: [],
    temps: 0,
    codegenNode: undefined,
    loc: locStub,
  }
}
