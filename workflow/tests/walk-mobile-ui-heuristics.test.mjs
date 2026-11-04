import assert from 'node:assert/strict';
import test from 'node:test';
import { findSettingsCardWrapper, hasInsetDescendantContent } from '../src/varde_workflow/skills/varde-review-ui/scripts/walk-mobile-ui-heuristics.mjs';

const settingsPageFixtures = [
  {
    name: 'settings layout with individually grouped sections',
    candidate: {
      visible: true, width: 358, viewportWidth: 390, height: 420,
      headingCount: 3, paddingInline: 16, borderRadius: 0,
      opaqueBackground: false, hasBorder: false,
    },
    expected: null,
  },
  {
    name: 'settings section with bottom divider',
    candidate: {
      visible: true, width: 358, viewportWidth: 390, height: 420,
      headingCount: 2, paddingInline: 16, borderRadius: 0,
      opaqueBackground: false, hasBorder: true,
    },
    expected: null,
  },
  {
    name: 'rounded card grouping multiple settings sections',
    candidate: {
      visible: true, width: 358, viewportWidth: 390, height: 420,
      headingCount: 2, paddingInline: 16, borderRadius: 12,
      opaqueBackground: true, hasBorder: true,
    },
    expected: 'card',
  },
];

test('settings wrapper detector distinguishes cards from layout sections', () => {
  for (const fixture of settingsPageFixtures) {
    const found = findSettingsCardWrapper([{ ...fixture.candidate, selector: fixture.name }]);
    assert.equal(found?.selector ?? null, fixture.expected === 'card' ? fixture.name : null, fixture.name);
  }
});

test('settings wrapper detector reports the smallest matching card wrapper', () => {
  const [outer, inner] = settingsPageFixtures.slice(2).concat(settingsPageFixtures.slice(2)).map((fixture, index) => ({
    ...fixture.candidate,
    selector: index === 0 ? 'outer' : 'inner',
    width: index === 0 ? 350 : 300,
    height: index === 0 ? 400 : 200,
  }));
  assert.equal(findSettingsCardWrapper([outer, inner]).selector, 'inner');
});

test('edge-padding walk skips full-bleed wrappers when descendant content has 16px gutters', () => {
  const fullBleedWithInsetContent = {
    left: 0,
    right: 390,
    viewportWidth: 390,
    descendants: [{ leftInset: 16, rightInset: 16 }, { leftInset: 16, rightInset: 24 }],
  };
  assert.equal(hasInsetDescendantContent(fullBleedWithInsetContent), true);
  assert.equal(hasInsetDescendantContent({
    ...fullBleedWithInsetContent,
    descendants: [{ leftInset: 0, rightInset: 16 }],
  }), false, 'edge-aligned descendant content must still be reported');
  assert.equal(hasInsetDescendantContent({
    ...fullBleedWithInsetContent,
    left: 8,
  }), false, 'only full-bleed containers are skipped');
});
