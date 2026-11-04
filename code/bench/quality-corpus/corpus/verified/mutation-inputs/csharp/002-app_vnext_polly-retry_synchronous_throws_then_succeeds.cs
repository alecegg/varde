[Benchmark]
public void Retry_Synchronous_Throws_Then_Succeeds()
{
    int count = 0;

    SyncPolicy.Execute(() =>
    {
        if (count++ % 2 == 0)
        {
            throw new InvalidOperationException();
        }
    });
}
