using Microsoft.Extensions.Options;
using RfidBridge.Options;

namespace RfidBridge.Services;

public static class RfidProviderFactory
{
    public static IRfidProvider Create(
        IServiceProvider services,
        IOptions<RfidBridgeOptions> options)
    {
        var providerName = options.Value.Provider?.Trim() ?? "Fake";
        if (providerName.Equals("ZebraSdk", StringComparison.OrdinalIgnoreCase))
        {
            return ActivatorUtilities.CreateInstance<ZebraSdkProvider>(services);
        }

        if (providerName.Equals("Fake", StringComparison.OrdinalIgnoreCase))
        {
            return ActivatorUtilities.CreateInstance<FakeRfidProvider>(services);
        }

        throw new RfidProviderException(
            $"Unsupported RFID provider '{providerName}'. Expected 'Fake' or 'ZebraSdk'."
        );
    }
}
