using RfidBridge.Contracts;

namespace RfidBridge.Services;

public sealed class FakeRfidProvider : IRfidProvider
{
    private Func<IReadOnlyList<RfidTag>, Task>? _onTags;
    private RfidStartRequest? _lastRequest;

    public string Name => "Fake";

    public Task StartAsync(
        RfidStartRequest request,
        Func<IReadOnlyList<RfidTag>, Task> onTags,
        CancellationToken cancellationToken
    )
    {
        _lastRequest = request;
        _onTags = onTags;
        return Task.CompletedTask;
    }

    public Task StopAsync(CancellationToken cancellationToken)
    {
        return Task.CompletedTask;
    }

    public Task ResetAsync(RfidStartRequest request, CancellationToken cancellationToken)
    {
        _lastRequest = request;
        return Task.CompletedTask;
    }

    public async Task PublishTagsAsync(IReadOnlyList<string> epcs, CancellationToken cancellationToken)
    {
        if (_onTags is null)
        {
            return;
        }

        var now = DateTimeOffset.UtcNow;
        var tags = epcs
            .Where(epc => !string.IsNullOrWhiteSpace(epc))
            .Select(epc => new RfidTag(epc.Trim().ToUpperInvariant(), now))
            .ToArray();

        if (tags.Length == 0)
        {
            return;
        }

        await _onTags(tags);
    }
}
