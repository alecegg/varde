function compileCode(source: string): string {
  console.clear()
  try {
    const errors: CompilerError[] = []
    const compileFn = ssrMode.value ? ssrCompile : compile
    const start = performance.now()
    const { code, ast, map } = compileFn(source, {
      ...compilerOptions,
      filename: 'ExampleTemplate.vue',
      sourceMap: true,
      onError: err => {
        errors.push(err)
      },
    })
    console.log(`Compiled in ${(performance.now() - start).toFixed(2)}ms.`)
    monaco.editor.setModelMarkers(
      editor.getModel()!,
      `@vue/compiler-dom`,
      errors.filter(e => e.loc).map(formatError),
    )
    console.log(`AST: `, ast)
    console.log(`Options: `, toRaw(compilerOptions))
    lastSuccessfulCode = code + `\n\n// Check the console for the AST`
    lastSuccessfulMap = new SourceMapConsumer(map!)
    lastSuccessfulMap!.computeColumnSpans()
  } catch (e: any) {
    lastSuccessfulCode = `/* ERROR: ${e.message} (see console for more info) */`
    console.error(e)
  }
  return lastSuccessfulCode
}
