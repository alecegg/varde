function commonAssertions(raw: (exp: ExpressionNode) => boolean) {
  const fn = (str: string) => raw(createSimpleExpression(str))
  // should work
  expect(fn('obj.foo')).toBe(true)
  expect(fn('obj[foo]')).toBe(true)
  expect(fn('obj[arr[0]]')).toBe(true)
  expect(fn('obj[arr[ret.bar]]')).toBe(true)
  expect(fn('obj[arr[ret[bar]]]')).toBe(true)
  expect(fn('obj[arr[ret[bar]]].baz')).toBe(true)
  expect(fn('obj[1 + 1]')).toBe(true)
  expect(fn(`obj[x[0]]`)).toBe(true)
  expect(fn('obj[1][2]')).toBe(true)
  expect(fn('obj[1][2].foo[3].bar.baz')).toBe(true)
  expect(fn(`a[b[c.d]][0]`)).toBe(true)
  expect(fn('obj?.foo')).toBe(true)
  expect(fn('foo().test')).toBe(true)

  // strings
  expect(fn(`a['foo' + bar[baz]["qux"]]`)).toBe(true)

  // multiline whitespaces
  expect(fn('obj \n .foo \n [bar \n + baz]')).toBe(true)
  expect(fn(`\n model\n.\nfoo \n`)).toBe(true)

  // should fail
  expect(fn('a \n b')).toBe(false)
  expect(fn('obj[foo')).toBe(false)
  expect(fn('objfoo]')).toBe(false)
  expect(fn('obj[arr[0]')).toBe(false)
  expect(fn('obj[arr0]]')).toBe(false)
  expect(fn('a + b')).toBe(false)
  expect(fn('foo()')).toBe(false)
  expect(fn('a?b:c')).toBe(false)
  expect(fn(`state['text'] = $event`)).toBe(false)
}
