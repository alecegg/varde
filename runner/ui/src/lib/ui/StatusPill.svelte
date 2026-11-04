<script module lang="ts">
  export const STATUS_LABELS = {
    running: 'Running',
    success: 'Succeeded',
    succeeded: 'Succeeded',
    waiting: 'Waiting',
    blocked: 'Blocked',
    'needs-input': 'Needs input',
    idle: 'Idle',
    paused: 'Paused',
    queued: 'Queued',
    open: 'Open',
    completed: 'Completed',
    failed: 'Failed',
    error: 'Failed',
    pending: 'Pending',
    cancelled: 'Cancelled',
    missing: 'Missing',
    unknown: 'Unknown',
    in_progress: 'In progress',
    needs_review: 'Needs review',
    done: 'Done',
    stale: 'Stale',
    alive: 'Available',
    claimed: 'Claimed',
    building: 'Building',
    in_review: 'In review',
    merged: 'Merged',
    rejected: 'Rejected',
    resolved: 'Resolved'
  } as const;
  export type StatusKey = keyof typeof STATUS_LABELS;
</script>

<script lang="ts">
  import Badge from './Badge.svelte';
  let { status, tone, label }: { status: StatusKey; tone?: 'neutral' | 'running' | 'success' | 'waiting' | 'blocked' | 'needs-input' | 'idle' | 'stalled' | 'danger'; label?: string } = $props();
</script>

<Badge {tone}>{label ?? STATUS_LABELS[status]}</Badge>
