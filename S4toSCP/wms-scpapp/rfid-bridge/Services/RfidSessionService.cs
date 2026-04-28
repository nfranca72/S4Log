using System.Collections.Concurrent;
using System.Threading.Channels;
using Microsoft.Extensions.Options;
using RfidBridge.Contracts;
using RfidBridge.Options;

namespace RfidBridge.Services;

public sealed class RfidSessionService
{
    private readonly IRfidProvider _provider;
    private readonly RfidBridgeOptions _options;
    private readonly ConcurrentDictionary<string, RfidTag> _tags = new(StringComparer.OrdinalIgnoreCase);
    private readonly ConcurrentDictionary<Channel<RfidEvent>, byte> _subscribers = new();
    private readonly SemaphoreSlim _gate = new(1, 1);
    private bool _connected;
    private bool _inventoryRunning;
    private RfidStartRequest? _currentRequest;

    public RfidSessionService(
        IRfidProvider provider,
        IOptions<RfidBridgeOptions> options)
    {
        _provider = provider;
        _options = options.Value;
    }

    public RfidConfiguration GetConfiguration()
    {
        var request = _currentRequest;
        return new RfidConfiguration(
            _provider.Name,
            request?.Host ?? _options.Host,
            request?.Port ?? _options.Port,
            request?.Antennas ?? _options.Antennas,
            ToIntDictionary(request?.TxPowers),
            ToIntDictionary(request?.RxSensitivity)
        );
    }

    public RfidState GetSnapshot()
    {
        var tags = _tags.Values
            .OrderBy(tag => tag.Epc, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        return new RfidState(
            _connected,
            _inventoryRunning,
            tags.Length,
            tags
        );
    }

    public ChannelReader<RfidEvent> Subscribe()
    {
        var channel = Channel.CreateUnbounded<RfidEvent>();
        _subscribers.TryAdd(channel, 0);
        channel.Writer.TryWrite(new RfidEvent("snapshot", DateTimeOffset.UtcNow, GetSnapshot()));
        return channel.Reader;
    }

    public void Unsubscribe(ChannelReader<RfidEvent> reader)
    {
        var channel = _subscribers.Keys.FirstOrDefault(candidate => candidate.Reader == reader);
        if (channel is null)
        {
            return;
        }

        if (_subscribers.TryRemove(channel, out _))
        {
            channel.Writer.TryComplete();
        }
    }

    public async Task<RfidState> StartAsync(RfidStartRequest request, CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            _currentRequest = NormalizeRequest(request);
            if (!_connected)
            {
                await _provider.StartAsync(_currentRequest, OnTagsAsync, cancellationToken);
                _connected = true;
            }

            _inventoryRunning = true;
        }
        finally
        {
            _gate.Release();
        }

        await PublishEventAsync("started");
        return GetSnapshot();
    }

    public async Task<RfidState> StopAsync(CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            await _provider.StopAsync(cancellationToken);
            _inventoryRunning = false;
        }
        finally
        {
            _gate.Release();
        }

        await PublishEventAsync("stopped");
        return GetSnapshot();
    }

    public async Task<RfidState> ResetAsync(RfidStartRequest request, CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            _tags.Clear();
            _currentRequest = NormalizeRequest(request);

            if (!_connected)
            {
                await _provider.StartAsync(_currentRequest, OnTagsAsync, cancellationToken);
                _connected = true;
            }

            await _provider.ResetAsync(_currentRequest, cancellationToken);
            _inventoryRunning = true;
        }
        finally
        {
            _gate.Release();
        }

        await PublishEventAsync("reset");
        return GetSnapshot();
    }

    private Task OnTagsAsync(IReadOnlyList<RfidTag> tags)
    {
        foreach (var tag in tags)
        {
            _tags[tag.Epc] = tag;
        }

        return PublishEventAsync("tags");
    }

    private Task PublishEventAsync(string type)
    {
        var evt = new RfidEvent(type, DateTimeOffset.UtcNow, GetSnapshot());
        foreach (var subscriber in _subscribers.Keys)
        {
            subscriber.Writer.TryWrite(evt);
        }

        return Task.CompletedTask;
    }

    private RfidStartRequest NormalizeRequest(RfidStartRequest request)
    {
        var antennas = request.Antennas
            .Where(antenna => antenna is >= 1 and <= 4)
            .Distinct()
            .OrderBy(antenna => antenna)
            .ToList();

        if (antennas.Count == 0)
        {
            antennas = _options.Antennas.ToList();
        }

        return new RfidStartRequest
        {
            Host = string.IsNullOrWhiteSpace(request.Host) ? _options.Host : request.Host.Trim(),
            Port = request.Port > 0 ? request.Port : _options.Port,
            Antennas = antennas,
            TxPowers = NormalizeAntennaMap(request.TxPowers, antennas),
            RxSensitivity = NormalizeAntennaMap(request.RxSensitivity, antennas),
        };
    }

    private static Dictionary<string, int> NormalizeAntennaMap(
        Dictionary<string, int>? values,
        IReadOnlyList<int> antennas)
    {
        var result = new Dictionary<string, int>();
        foreach (var antenna in antennas)
        {
            var key = antenna.ToString();
            result[key] = values is not null && values.TryGetValue(key, out var value)
                ? value
                : 0;
        }

        return result;
    }

    private static Dictionary<int, int> ToIntDictionary(Dictionary<string, int>? values)
    {
        var result = new Dictionary<int, int>();
        if (values is null)
        {
            return result;
        }

        foreach (var pair in values)
        {
            if (int.TryParse(pair.Key, out var antenna))
            {
                result[antenna] = pair.Value;
            }
        }

        return result;
    }
}
