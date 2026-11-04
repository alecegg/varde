public override HealthInfo GetHealthInfo()
{
    UpdateCurrentWindow();

    var successes = 0;
    var failures = 0;
    foreach (var window in _windows)
    {
        successes += window.Successes;
        failures += window.Failures;
    }

    return HealthInfo.Create(successes, failures);
}
