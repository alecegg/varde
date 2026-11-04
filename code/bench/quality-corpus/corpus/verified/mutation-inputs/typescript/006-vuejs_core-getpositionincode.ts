function getPositionInCode(
  code: string,
  token: string,
  expectName: string | boolean = false,
): Pos {
  const generatedOffset = code.indexOf(token)
  let line = 1
  let lastNewLinePos = -1
  for (let i = 0; i < generatedOffset; i++) {
    if (code.charCodeAt(i) === 10 /* newline char code */) {
      line++
      lastNewLinePos = i
    }
  }
  const res: Pos = {
    line,
    column:
      lastNewLinePos === -1
        ? generatedOffset
        : generatedOffset - lastNewLinePos - 1,
  }
  if (expectName) {
    res.name = typeof expectName === 'string' ? expectName : token
  }
  return res
}
