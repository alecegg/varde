#!/usr/bin/env bash
set -euo pipefail

# Exercise the public CLI in disposable storage, with synthetic reviewer evidence.
python3 - <<'PY'
import json
import os
from pathlib import Path
import subprocess
import tempfile

with tempfile.TemporaryDirectory(prefix='varde-group-gates-') as temporary:
    root = Path(temporary)
    repo = root / 'repo'
    repo.mkdir()
    env = dict(os.environ, VARDE_CONFIG_DIR=str(root / 'config'))
    for key in ('VARDE_WORKING_DIR', 'VARDE_KNOWLEDGE_DIR'):
        env.pop(key, None)

    def git(*args):
        subprocess.run(['git', *args], cwd=repo, env=env, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def cli(*args, code=0):
        result = subprocess.run(['varde-workflow', *map(str, args), '--json'],
                                cwd=repo, env=env, capture_output=True, text=True)
        assert result.returncode == code, (args, result.returncode, result.stdout, result.stderr)
        value = json.loads(result.stdout)
        assert value['ok'] == (code == 0), value
        return value.get('data', {})

    git('init', '-q')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'user.name', 'Group Gate Fixture')
    (repo / 'src').mkdir()
    (repo / 'src/feature.txt').write_text('before\n')
    git('add', '.')
    git('commit', '-qm', 'initial')
    working = root / 'working'
    cli('paths', 'set', '--project', repo, '--working', working,
        '--knowledge', root / 'knowledge')
    group = working / 'plans/group/plan.md'
    group.parent.mkdir(parents=True)
    group.write_text('---\ntype: plan\nid: group\nstatus: backlog\nshape: group\n'
                     'title: Group fixture\n---\n\n## Aggregate contract\n\n'
                     'Scope: src. Child: first; dependencies: none; contract: add feature.\n'
                     'Verification: inspect feature output and combined source.\n\n'
                     '## Acceptance criteria\n\n- [x] Combined fixture source is verified.\n')
    child = group.parent / 'first/plan.md'
    child.parent.mkdir()
    child.write_text('---\ntype: plan\nid: group/first\nstatus: completed\n'
                     'title: Completed child fixture\ndepends_on: []\n---\n\nChild complete.\n')
    cli('transition', group, 'active', code=4)
    created = cli('review', 'init', '--plan', group, '--repository', repo, '--scope', 'src')
    subject = created['subject']['subject_id']
    cli('review', 'check', '--subject', subject, '--checkpoint', 'start', code=4)

    def approve(phase):
        inspection = cli('review', 'inspect', '--subject', subject, '--phase', phase)
        record = dict(schema_version=1, subject_id=subject, phase=phase,
                      reviewer=dict(identity='synthetic-group-reviewer', provenance='test-fixture'),
                      verdict='approved', unresolved_choices=[],
                      contract_fingerprint=inspection['contract_fingerprint'],
                      baseline_id=inspection['baseline_id'],
                      verification_approach='inspect combined fixture source',
                      verification_rationale='fixture exercises public gate lifecycle',
                      verification_expected_results='group completes only with current final evidence',
                      rationale='synthetic test evidence')
        if phase == 'pre-edit':
            record.update(structural_risk='medium', structural_risk_rationale='aggregate shared contract',
                          implementation_review_required=True)
        else:
            record.update(change_fingerprint=inspection['change_fingerprint'],
                          coverage='entire-subject-change')
        evidence = root / (phase + '.json')
        evidence.write_text(json.dumps(record))
        cli('review', 'record', '--subject', subject, '--expected-version',
            inspection['version'], '--file', evidence)

    approve('pre-edit')
    assert cli('review', 'check', '--subject', subject, '--checkpoint', 'start')['ready']
    cli('transition', group, 'active')
    before_resume = group.read_bytes()
    assert cli('review', 'check', '--subject', subject, '--checkpoint', 'resume')['ready']
    assert group.read_bytes() == before_resume
    (repo / 'src/feature.txt').write_text('after\n')
    cli('review', 'check', '--subject', subject, '--checkpoint', 'complete', code=4)
    cli('conclude', group, code=4)
    approve('implementation')
    assert cli('review', 'check', '--subject', subject, '--checkpoint', 'complete')['ready']
    cli('conclude', group)
    assert 'status: completed' in group.read_text()
print('PASS: group activation, resume and conclusion require own current aggregate review evidence')
PY
