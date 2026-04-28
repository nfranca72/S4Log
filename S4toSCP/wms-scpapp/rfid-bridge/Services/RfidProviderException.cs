namespace RfidBridge.Services;

public sealed class RfidProviderException : Exception
{
    public RfidProviderException(string message)
        : base(message)
    {
    }

    public RfidProviderException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
