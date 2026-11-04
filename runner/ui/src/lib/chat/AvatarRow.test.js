import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import AvatarRow from './AvatarRow.svelte';

const chips = [
  { id: 'manager', label: 'Manager', initials: 'M', hue: 'violet', dot: null, needsYou: 2, href: '/thread/manager' },
  { id: 'builder', label: 'Builder', initials: 'B', hue: 'blue', dot: 'running', needsYou: 0, href: '/thread/builder' },
];

describe('AvatarRow', () => {
  it('renders one needs-you chip and agent chips with the same chip structure', () => {
    const { body } = render(AvatarRow, { props: { chips, activeId: 'builder', needsOpen: false, onToggleNeeds: () => {} } });

    expect(body).toContain('data-needs-chip');
    expect(body).toContain('Show 2 items needing you');
    expect(body).toContain('href="/thread/builder"');
    expect(body.match(/class="chip/g)).toHaveLength(3);
    expect(body.match(/class="circle/g)).toHaveLength(3);
    expect(body.match(/class="label/g)).toHaveLength(3);
    expect(body).toContain('href="/thread/manager"');
    expect(body).toMatch(/class="chip person [^"]*active/);
  });

  it('shows an empty needs-you chip without a count badge', () => {
    const { body } = render(AvatarRow, { props: { chips: chips.map((chip) => ({ ...chip, needsYou: 0 })), activeId: '', needsOpen: false, onToggleNeeds: () => {} } });

    expect(body).toMatch(/class="chip needs-chip [^"]*is-empty/);
    expect(body).not.toMatch(/class="count(?:\s|svelte-)/);
  });

  it('uses the mailbox-wide count when it is provided', () => {
    const { body } = render(AvatarRow, { props: { chips, activeId: '', needsOpen: false, needsCount: 7, onToggleNeeds: () => {} } });

    expect(body).toContain('Show 7 items needing you');
    expect(body).toContain('>7</span>');
  });
});
