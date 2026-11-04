public static object CreateOpenedCircuitBreaker(PollyVersion version, bool handleOutcome)
{
    var manualControl = new CircuitBreakerManualControl();
    var options = new CircuitBreakerStrategyOptions
    {
        ShouldHandle = _ => PredicateResult.True(),
        ManualControl = manualControl,
    };

    if (version == PollyVersion.V8)
    {
        var builder = new ResiliencePipelineBuilder();

        if (handleOutcome)
        {
            builder.AddStrategy(_ => new OutcomeHandlingStrategy(), new EmptyResilienceOptions());
        }

        var strategy = builder.AddCircuitBreaker(options).Build();
        manualControl.IsolateAsync().GetAwaiter().GetResult();
        return strategy;
    }
    else
    {
        var policy = Policy.HandleResult<string>(r => true).AdvancedCircuitBreakerAsync(options.FailureRatio, options.SamplingDuration, options.MinimumThroughput, options.BreakDuration);
        policy.Isolate();
        return policy;
    }
}
