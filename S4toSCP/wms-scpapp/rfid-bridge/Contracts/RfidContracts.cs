namespace RfidBridge.Contracts;

public sealed record RfidConfiguration(
    string Provider,
    string Host,
    int Port,
    IReadOnlyList<int> Antennas,
    IReadOnlyDictionary<int, int> TxPowers,
    IReadOnlyDictionary<int, int> RxSensitivity
);

public sealed class RfidStartRequest
{
    public string Host { get; set; } = string.Empty;
    public int Port { get; set; }
    public List<int> Antennas { get; set; } = [];
    public Dictionary<string, int>? TxPowers { get; set; }
    public Dictionary<string, int>? RxSensitivity { get; set; }
}

public sealed record RfidTag(
    string Epc,
    DateTimeOffset SeenAtUtc
);

public sealed record RfidState(
    bool Connected,
    bool InventoryRunning,
    int TagCount,
    IReadOnlyList<RfidTag> Tags
);

public sealed record RfidEvent(
    string Type,
    DateTimeOffset OccurredAtUtc,
    RfidState State
);

public sealed record MockTagsRequest(
    IReadOnlyList<string> Tags
);
