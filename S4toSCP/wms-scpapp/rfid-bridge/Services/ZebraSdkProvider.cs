using System.Collections;
using System.Reflection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using RfidBridge.Contracts;
using RfidBridge.Options;

namespace RfidBridge.Services;

public sealed class ZebraSdkProvider : IRfidProvider, IAsyncDisposable
{
    private readonly ILogger<ZebraSdkProvider> _logger;
    private readonly RfidBridgeOptions _options;
    private Func<IReadOnlyList<RfidTag>, Task>? _onTags;
    private CancellationTokenSource? _pollingCts;
    private Task? _pollingTask;
    private Assembly? _sdkAssembly;
    private dynamic? _reader;
    private bool _inventoryRunning;

    public ZebraSdkProvider(
        IOptions<RfidBridgeOptions> options,
        ILogger<ZebraSdkProvider> logger)
    {
        _options = options.Value;
        _logger = logger;
    }

    public string Name => "ZebraSdk";

    public async Task StartAsync(
        RfidStartRequest request,
        Func<IReadOnlyList<RfidTag>, Task> onTags,
        CancellationToken cancellationToken)
    {
        _onTags = onTags;

        try
        {
            EnsureSdkLoaded();
            await EnsureConnectedAsync(request, cancellationToken);
            StartInventoryInternal();
            StartPollingLoop();
        }
        catch (Exception ex) when (ex is not RfidProviderException)
        {
            throw new RfidProviderException("Failed to start Zebra SDK RFID provider.", ex);
        }
    }

    public async Task StopAsync(CancellationToken cancellationToken)
    {
        try
        {
            StopInventoryInternal();
            await StopPollingLoopAsync();
        }
        catch (Exception ex) when (ex is not RfidProviderException)
        {
            throw new RfidProviderException("Failed to stop Zebra SDK RFID provider.", ex);
        }
    }

    public async Task ResetAsync(RfidStartRequest request, CancellationToken cancellationToken)
    {
        try
        {
            EnsureSdkLoaded();
            await EnsureConnectedAsync(request, cancellationToken);
            TryInvokeIfExists(_reader?.Actions, "Reset");
            StopInventoryInternal();
            StartInventoryInternal();
            StartPollingLoop();
        }
        catch (Exception ex) when (ex is not RfidProviderException)
        {
            throw new RfidProviderException("Failed to reset Zebra SDK RFID provider.", ex);
        }
    }

    public async ValueTask DisposeAsync()
    {
        await StopPollingLoopAsync();
        DisconnectReader();
    }

    private void EnsureSdkLoaded()
    {
        if (_sdkAssembly is not null)
        {
            return;
        }

        var sdkOptions = _options.ZebraSdk;
        if (!OperatingSystem.IsWindows())
        {
            throw new RfidProviderException(
                "ZebraSdkProvider requires Windows because the official Zebra Host RFID SDK is Windows-based."
            );
        }

        var assemblyPath = ResolveAssemblyPath(sdkOptions.AssemblyPath);
        if (assemblyPath is null)
        {
            throw new RfidProviderException(
                "Zebra Host RFID SDK assembly not found. Configure "
                + "RfidBridge:ZebraSdk:AssemblyPath or place Symbol.RFID3.Host.dll under Utilities\\ZebraSdk."
            );
        }

        _logger.LogInformation("Loading Zebra Host RFID SDK from {AssemblyPath}", assemblyPath);
        _sdkAssembly = Assembly.LoadFrom(assemblyPath);
    }

    private static string? ResolveAssemblyPath(string configuredPath)
    {
        const string assemblyFileName = "Symbol.RFID3.Host.dll";

        if (!string.IsNullOrWhiteSpace(configuredPath))
        {
            var expandedPath = Environment.ExpandEnvironmentVariables(configuredPath.Trim());
            foreach (var candidate in CandidatePaths(expandedPath))
            {
                if (File.Exists(candidate))
                {
                    return Path.GetFullPath(candidate);
                }
            }
        }

        foreach (var basePath in AncestorPaths(Directory.GetCurrentDirectory())
                     .Concat(AncestorPaths(AppContext.BaseDirectory))
                     .Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var repoCandidate = Path.Combine(basePath, "Utilities", "ZebraSdk", assemblyFileName);
            if (File.Exists(repoCandidate))
            {
                return Path.GetFullPath(repoCandidate);
            }
        }

        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        if (!string.IsNullOrWhiteSpace(programFiles))
        {
            var installedCandidate = Path.Combine(
                programFiles,
                "Zebra Technologies",
                "123RFID Desktop",
                assemblyFileName
            );
            if (File.Exists(installedCandidate))
            {
                return Path.GetFullPath(installedCandidate);
            }
        }

        return null;
    }

    private static IEnumerable<string> CandidatePaths(string path)
    {
        if (Path.IsPathRooted(path))
        {
            yield return path;
            yield break;
        }

        foreach (var basePath in AncestorPaths(Directory.GetCurrentDirectory())
                     .Concat(AncestorPaths(AppContext.BaseDirectory))
                     .Distinct(StringComparer.OrdinalIgnoreCase))
        {
            yield return Path.Combine(basePath, path);
        }
    }

    private static IEnumerable<string> AncestorPaths(string startPath)
    {
        var directory = new DirectoryInfo(startPath);
        while (directory is not null)
        {
            yield return directory.FullName;
            directory = directory.Parent;
        }
    }

    private async Task EnsureConnectedAsync(RfidStartRequest request, CancellationToken cancellationToken)
    {
        if (_reader is not null && IsReaderConnected())
        {
            return;
        }

        cancellationToken.ThrowIfCancellationRequested();

        var readerType = _sdkAssembly?.GetType(_options.ZebraSdk.ReaderTypeName, throwOnError: false);
        if (readerType is null)
        {
            throw new RfidProviderException(
                $"Unable to find Zebra RFID reader type '{_options.ZebraSdk.ReaderTypeName}' in SDK assembly."
            );
        }

        object?[] constructorArgs = [request.Host, (uint)request.Port, _options.ZebraSdk.ConnectionTimeout];
        _reader = Activator.CreateInstance(readerType, constructorArgs);
        if (_reader is null)
        {
            throw new RfidProviderException("Unable to create Zebra RFID reader instance.");
        }

        await Task.Run(() =>
        {
            _reader.Connect();
            ApplyAntennaConfiguration(request);
        }, cancellationToken);
    }

    private void ApplyAntennaConfiguration(RfidStartRequest request)
    {
        foreach (var antenna in request.Antennas)
        {
            try
            {
                ApplySingleAntennaConfiguration(antenna, request);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(
                    ex,
                    "Failed to apply Zebra SDK antenna configuration for antenna {Antenna}. The inventory will continue with reader defaults.",
                    antenna
                );
            }
        }
    }

    private void ApplySingleAntennaConfiguration(int antenna, RfidStartRequest request)
    {
        var configApi = _reader?.Config?.Antennas;
        if (configApi is null)
        {
            return;
        }

        var antennaConfig = TryGetAntennaRfConfig(configApi, antenna);
        if (antennaConfig is null)
        {
            return;
        }

        if (request.TxPowers is not null && request.TxPowers.TryGetValue(antenna.ToString(), out var txPower))
        {
            SetPropertyIfExists(antennaConfig, "TransmitPower", txPower);
            SetPropertyIfExists(antennaConfig, "TransmitPowerIndex", txPower);
        }

        if (request.RxSensitivity is not null && request.RxSensitivity.TryGetValue(antenna.ToString(), out var rxSensitivity))
        {
            SetPropertyIfExists(antennaConfig, "ReceiveSensitivity", rxSensitivity);
            SetPropertyIfExists(antennaConfig, "ReceiveSensitivityIndex", rxSensitivity);
            SetPropertyIfExists(antennaConfig, "RxSensitivityIndex", rxSensitivity);
        }

        if (TrySetAntennaRfConfig(configApi, antenna, antennaConfig))
        {
            return;
        }

        TryInvokeIfExists(configApi, "SetAntennaConfig", (ushort)antenna, antennaConfig);
    }

    private static object? TryGetAntennaRfConfig(object antennas, int antenna)
    {
        var antennaProperties = GetIndexedProperty(antennas, antenna);
        if (antennaProperties is not null)
        {
            return TryInvoke(antennaProperties, "GetRfConfig")
                ?? TryInvoke(antennaProperties, "GetConfig");
        }

        return TryInvoke(antennas, "GetAntennaConfig", (ushort)antenna)
            ?? TryInvoke(antennas, "GetAntennaConfig", antenna);
    }

    private static bool TrySetAntennaRfConfig(object antennas, int antenna, object antennaConfig)
    {
        var antennaProperties = GetIndexedProperty(antennas, antenna);
        if (antennaProperties is null)
        {
            return false;
        }

        return TryInvokeVoid(antennaProperties, "SetRfConfig", antennaConfig)
            || TryInvokeVoid(antennaProperties, "SetConfig", antennaConfig);
    }

    private static object? GetIndexedProperty(object target, int index)
    {
        var property = target.GetType().GetProperty("Item", BindingFlags.Instance | BindingFlags.Public);
        if (property is null)
        {
            return null;
        }

        try
        {
            return property.GetValue(target, [index]);
        }
        catch
        {
            return null;
        }
    }

    private void StartInventoryInternal()
    {
        if (_reader is null || _inventoryRunning)
        {
            return;
        }

        _reader.Actions.Inventory.Perform();
        _inventoryRunning = true;
    }

    private void StopInventoryInternal()
    {
        if (_reader is null)
        {
            return;
        }

        TryInvokeIfExists(_reader.Actions?.Inventory, "Stop");
        _inventoryRunning = false;
    }

    private void StartPollingLoop()
    {
        if (_onTags is null)
        {
            return;
        }

        if (_pollingTask is not null && !_pollingTask.IsCompleted)
        {
            return;
        }

        _pollingCts = new CancellationTokenSource();
        _pollingTask = Task.Run(() => PollTagsLoopAsync(_pollingCts.Token));
    }

    private async Task StopPollingLoopAsync()
    {
        if (_pollingCts is null || _pollingTask is null)
        {
            return;
        }

        _pollingCts.Cancel();
        try
        {
            await _pollingTask;
        }
        catch (OperationCanceledException)
        {
        }
        finally
        {
            _pollingCts.Dispose();
            _pollingCts = null;
            _pollingTask = null;
        }
    }

    private async Task PollTagsLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                var tags = ReadTagsSnapshot();
                if (tags.Count > 0 && _onTags is not null)
                {
                    await _onTags(tags);
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Zebra SDK polling failed.");
            }

            await Task.Delay(Math.Max(50, _options.ZebraSdk.PollIntervalMs), cancellationToken);
        }
    }

    private List<RfidTag> ReadTagsSnapshot()
    {
        if (_reader is null)
        {
            return [];
        }

        var rawTags = TryGetReadTags();
        if (rawTags is null)
        {
            return [];
        }

        var now = DateTimeOffset.UtcNow;
        var tags = new List<RfidTag>();
        foreach (var rawTag in rawTags)
        {
            var epc = ReadTagId(rawTag);
            if (string.IsNullOrWhiteSpace(epc))
            {
                continue;
            }

            tags.Add(new RfidTag(epc.Trim().ToUpperInvariant(), now));
        }

        return tags;
    }

    private IEnumerable<object>? TryGetReadTags()
    {
        object?[] args = [1000];
        var sources = new object?[] { _reader?.Actions, _reader?.Actions?.Inventory, _reader };
        foreach (var source in sources)
        {
            if (source is null)
            {
                continue;
            }

            var result = TryInvoke(source, "GetReadTags", args)
                ?? TryInvoke(source, "GetReadTagsEx", args);

            if (result is IEnumerable enumerable and not string)
            {
                return enumerable.Cast<object>().ToArray();
            }
        }

        return null;
    }

    private static string? ReadTagId(object rawTag)
    {
        var type = rawTag.GetType();
        var candidates = new[] { "TagID", "TagId", "TagIDHex", "EPC", "Epc" };
        foreach (var candidate in candidates)
        {
            var property = type.GetProperty(candidate, BindingFlags.Instance | BindingFlags.Public);
            if (property?.GetValue(rawTag) is { } value)
            {
                return value.ToString();
            }
        }

        return null;
    }

    private bool IsReaderConnected()
    {
        if (_reader is null)
        {
            return false;
        }

        var property = _reader.GetType().GetProperty("IsConnected", BindingFlags.Instance | BindingFlags.Public);
        return property?.GetValue(_reader) as bool? ?? false;
    }

    private void DisconnectReader()
    {
        if (_reader is null)
        {
            return;
        }

        try
        {
            StopInventoryInternal();
            TryInvokeIfExists(_reader, "Disconnect");
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to disconnect Zebra RFID reader cleanly.");
        }
        finally
        {
            _reader = null;
        }
    }

    private static void SetPropertyIfExists(object target, string propertyName, object value)
    {
        var property = target.GetType().GetProperty(propertyName, BindingFlags.Instance | BindingFlags.Public);
        if (property is null || !property.CanWrite)
        {
            return;
        }

        var converted = Convert.ChangeType(value, property.PropertyType);
        property.SetValue(target, converted);
    }

    private static object? TryInvoke(object target, string methodName, params object?[]? args)
    {
        var methods = target.GetType()
            .GetMethods(BindingFlags.Instance | BindingFlags.Public)
            .Where(method => method.Name == methodName)
            .ToArray();

        foreach (var method in methods)
        {
            var parameters = method.GetParameters();
            var values = args ?? [];
            if (parameters.Length != values.Length)
            {
                continue;
            }

            try
            {
                return method.Invoke(target, values);
            }
            catch
            {
            }
        }

        return null;
    }

    private static void TryInvokeIfExists(object? target, string methodName, params object?[]? args)
    {
        if (target is null)
        {
            return;
        }

        _ = TryInvoke(target, methodName, args);
    }

    private static bool TryInvokeVoid(object target, string methodName, params object?[]? args)
    {
        var methods = target.GetType()
            .GetMethods(BindingFlags.Instance | BindingFlags.Public)
            .Where(method => method.Name == methodName)
            .ToArray();

        foreach (var method in methods)
        {
            var parameters = method.GetParameters();
            var values = args ?? [];
            if (parameters.Length != values.Length)
            {
                continue;
            }

            try
            {
                method.Invoke(target, values);
                return true;
            }
            catch
            {
            }
        }

        return false;
    }
}
