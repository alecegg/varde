export function isReferencedIdentifier(
  id: Identifier,
  parent: Node | null,
  parentStack: Node[],
): boolean {
  if (__BROWSER__) {
    return false
  }

  if (!parent) {
    return true
  }

  // is a special keyword but parsed as identifier
  if (id.name === 'arguments') {
    return false
  }

  if (isReferenced(id, parent, parentStack[parentStack.length - 2])) {
    return true
  }

  // babel's isReferenced check returns false for ids being assigned to, so we
  // need to cover those cases here
  switch (parent.type) {
    case 'AssignmentExpression':
    case 'AssignmentPattern':
      return true
    case 'ObjectProperty':
      return parent.key !== id && isInDestructureAssignment(parent, parentStack)
    case 'ArrayPattern':
      return isInDestructureAssignment(parent, parentStack)
  }

  return false
}
