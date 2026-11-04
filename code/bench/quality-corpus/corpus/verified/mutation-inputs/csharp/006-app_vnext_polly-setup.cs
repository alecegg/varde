[GlobalSetup]
public void Setup()
{
    _meterListener = MeteringUtil.ListenPollyMetrics();
    _pipelineV7 = Helper.CreateStrategyPipeline(PollyVersion.V7, false);
    _pipelineV8 = Helper.CreateStrategyPipeline(PollyVersion.V8, false);
    _pipelineTelemetryV8 = Helper.CreateStrategyPipeline(PollyVersion.V8, true);
    _nonGeneric = Helper.CreateNonGenericStrategyPipeline(telemetry: false);
    _nonGenericTelemetry = Helper.CreateNonGenericStrategyPipeline(telemetry: true);
}
