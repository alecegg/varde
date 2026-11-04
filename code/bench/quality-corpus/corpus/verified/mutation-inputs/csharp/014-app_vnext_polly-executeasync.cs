public static async ValueTask ExecuteAsync(this object obj, PollyVersion version)
{
    switch (version)
    {
        case PollyVersion.V7:
            await ((IAsyncPolicy<string>)obj).ExecuteAsync(static _ => Task.FromResult("dummy"), CancellationToken.None).ConfigureAwait(false);
            return;
        case PollyVersion.V8:
            var context = ResilienceContextPool.Shared.Get();

            await ((ResiliencePipeline<string>)obj).ExecuteOutcomeAsync(
                static (_, _) => Outcome.FromResultAsValueTask("dummy"),
                context,
                string.Empty).ConfigureAwait(false);

            ResilienceContextPool.Shared.Return(context);
            return;
    }

    throw new NotSupportedException();
}
