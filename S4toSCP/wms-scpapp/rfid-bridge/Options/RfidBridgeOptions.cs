namespace RfidBridge.Options;

public sealed class RfidBridgeOptions
{
    public const string SectionName = "RfidBridge";

    public string Provider { get; set; } = "Fake";
    public string Host { get; set; } = "127.0.0.1";
    public int Port { get; set; } = 5084;
    public List<int> Antennas { get; set; } = [];
    public ZebraSdkOptions ZebraSdk { get; set; } = new();
}

public sealed class ZebraSdkOptions
{
    public string AssemblyPath { get; set; } = string.Empty;
    public string ReaderTypeName { get; set; } = "Symbol.RFID3.RFIDReader";
    public uint ConnectionTimeout { get; set; } = 30;
    public int PollIntervalMs { get; set; } = 250;
}
