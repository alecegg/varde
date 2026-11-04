internal IDisposable Initialize(Func<ResilienceContext, Task> onIsolate, Func<ResilienceContext, Task> onReset)
{
    bool isolated;
    lock (_lock)
    {
        _onIsolate.Add(onIsolate);
        _onReset.Add(onReset);
        isolated = _isolated;
    }

    // if the control indicates that circuit breaker should be isolated, we isolate it right away
    if (isolated)
    {
        var context = ResilienceContextPool.Shared.Get().Initialize<VoidResult>(isSynchronous: true);
        onIsolate(context).GetAwaiter().GetResult();
    }

    return new RegistrationDisposable(this, onIsolate, onReset);
}
