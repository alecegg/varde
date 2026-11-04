public async ValueTask DisposeAsync()
{
    if (_component is not null)
    {
        await _component.DisposeAsync().ConfigureAwait(false);
        _component = null;
    }

    GC.SuppressFinalize(this);
}
