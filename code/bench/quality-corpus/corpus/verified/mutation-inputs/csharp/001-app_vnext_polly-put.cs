public void Put(string key, object? value, Ttl ttl)
{
    TimeSpan remaining = DateTimeOffset.MaxValue - DateTimeOffset.UtcNow;
    var options = new MemoryCacheEntryOptions();

    if (ttl.SlidingExpiration)
    {
        options.SlidingExpiration = ttl.Timespan < remaining ? ttl.Timespan : remaining;
    }
    else
    {
        if (ttl.Timespan == TimeSpan.MaxValue)
        {
            options.AbsoluteExpiration = DateTimeOffset.MaxValue;
        }
        else
        {
            options.AbsoluteExpirationRelativeToNow = ttl.Timespan < remaining ? ttl.Timespan : remaining;
        }
    }

    _cache.Set(key, value, options);
}
