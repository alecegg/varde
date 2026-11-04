export function findSettingsCardWrapper(candidates) {
  return candidates
    .filter((candidate) => candidate.visible
      && candidate.width < candidate.viewportWidth - 1
      && candidate.height >= 80
      && candidate.headingCount >= 2
      && candidate.paddingInline >= 8
      && candidate.borderRadius >= 8
      && (candidate.opaqueBackground || candidate.hasBorder))
    .sort((a, b) => a.width * a.height - b.width * b.height)[0] ?? null;
}

export function hasInsetDescendantContent({ left, right, viewportWidth, descendants }) {
  const fullBleed = left <= 1 && viewportWidth - right <= 1;
  return fullBleed && descendants.length > 0 && descendants.every(({ leftInset, rightInset }) => (
    leftInset >= 16 && rightInset >= 16
  ));
}
