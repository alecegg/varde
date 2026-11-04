[UnconditionalSuppressMessage(
    "Trimming",
    "IL2026:Members annotated with 'RequiresUnreferencedCodeAttribute' require dynamic access otherwise can break functionality when trimming application code",
    Justification = "All options members preserved.")]
[DynamicDependency(DynamicallyAccessedMemberTypes.All, typeof(CircuitBreakerStrategyOptions))]
public static ResiliencePipelineBuilder AddCircuitBreaker(this ResiliencePipelineBuilder builder, CircuitBreakerStrategyOptions options)
{
    Guard.NotNull(builder);
    Guard.NotNull(options);

    return builder.AddStrategy(context => CreateStrategy(context, options), options);
}
