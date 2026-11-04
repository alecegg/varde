    public Task ScheduleTask(Func<Task> taskFactory)
    {
#if NET8_0_OR_GREATER
        ObjectDisposedException.ThrowIf(_disposed, this);
#else
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(ScheduledTaskExecutor));
        }
#endif

        var source = new TaskCompletionSource<object>(TaskCreationOptions.RunContinuationsAsynchronously);

        _tasks.Enqueue(new Entry(taskFactory, source));
        _semaphore.Release();
        return source.Task;
    }
