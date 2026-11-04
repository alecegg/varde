[Benchmark]
public async ValueTask ExecuteAsync_Exception_V7()
{
    try
    {
        await _policy!.ExecuteAsync(_ => Task.FromResult("dummy"), CancellationToken.None).ConfigureAwait(false);
    }
    catch (BrokenCircuitException)
    {
        // ok
    }
}
