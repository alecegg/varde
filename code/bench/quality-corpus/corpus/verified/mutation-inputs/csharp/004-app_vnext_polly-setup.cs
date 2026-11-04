[GlobalSetup]
public void Setup()
{
    var first = PipelineComponent.Empty;
    var second = PipelineComponent.Empty;
    var source = new ResilienceTelemetrySource("pipeline", "instance", "strategy");
    var telemetry = new ResilienceStrategyTelemetry(source, null);
    var components = new[] { first, second };

    _component = CompositeComponent.Create(components, telemetry, TimeProvider.System);
    _context = ResilienceContextPool.Shared.Get(CancellationToken.None);
}
