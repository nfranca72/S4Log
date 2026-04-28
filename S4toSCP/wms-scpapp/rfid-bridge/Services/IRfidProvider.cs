using RfidBridge.Contracts;

namespace RfidBridge.Services;

public interface IRfidProvider
{
    string Name { get; }
    Task StartAsync(
        RfidStartRequest request,
        Func<IReadOnlyList<RfidTag>, Task> onTags,
        CancellationToken cancellationToken
    );
    Task StopAsync(CancellationToken cancellationToken);
    Task ResetAsync(RfidStartRequest request, CancellationToken cancellationToken);
}
