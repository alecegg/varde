import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import AppHeader from './AppHeader.svelte';

describe('AppHeader connection state', () => {
  it('does not render persistent connection labels', () => {
    const forbiddenLabels = [
      ['On', 'line'].join(''),
      ['Re', 'trying'].join(''),
      ['Connec', 'ting'].join(''),
    ];
    const { body } = render(AppHeader, {
      props: {
        title: 'Chats',
        iconPath: '/favicon.svg',
      },
    });

    for (const label of forbiddenLabels) expect(body).not.toContain(label);
  });
});
