[GlobalSetup]
public void Prepare()
{
    _pipeline = Build(new ResiliencePipelineBuilder());

    if (Telemetry)
    {
        _meterListener = MeteringUtil.ListenPollyMetrics();
    }
}
