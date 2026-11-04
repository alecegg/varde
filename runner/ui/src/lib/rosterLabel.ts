type RosterIdentity = { id: string; name: string };

export function profileLinkLabel(identity: RosterIdentity, identities: RosterIdentity[] = [identity]): string {
  const name = identity.name.trim();
  const nameIsUnique = identities.filter((item) => item.name.trim() === name).length === 1;
  return `Edit ${name && nameIsUnique ? name : identity.id} profile`;
}

export function profileLinkLabels(identities: RosterIdentity[]): Record<string, string> {
  return Object.fromEntries(identities.map((identity) => [identity.id, profileLinkLabel(identity, identities)]));
}
