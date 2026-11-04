public Task IsolateCircuitAsync(ResilienceContext context)
{
    EnsureNotDisposed();

    context.Initialize<T>(isSynchronous: false);

    Task task;

    lock (_lock)
    {
        var exception = new IsolatedCircuitException();
        _telemetry.SetTelemetrySource(exception);
        SetLastHandledOutcome_NeedsLock(Outcome.FromException<T>(exception));
        task = OpenCircuitFor_NeedsLock(Outcome.FromResult<T>(default), TimeSpan.MaxValue, manual: true, context);
        _circuitState = CircuitState.Isolated;
    }

    return ExecuteScheduledTaskAsync(task, context);
}
