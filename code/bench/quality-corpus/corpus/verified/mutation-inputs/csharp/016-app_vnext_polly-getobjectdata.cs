public override void GetObjectData(SerializationInfo info, StreamingContext context)
{
    Guard.NotNull(info);
    if (RetryAfter.HasValue)
    {
        info.AddValue("RetryAfter", RetryAfter.Value.Ticks);
    }

    base.GetObjectData(info, context);
}
