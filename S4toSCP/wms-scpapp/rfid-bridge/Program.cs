using System.Text.Json;
using RfidBridge.Contracts;
using RfidBridge.Options;
using RfidBridge.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Logging.ClearProviders();
builder.Logging.AddConsole();

builder.Services.Configure<RfidBridgeOptions>(
    builder.Configuration.GetSection(RfidBridgeOptions.SectionName)
);
builder.Services.AddSingleton<IRfidProvider>(serviceProvider =>
{
    var options = serviceProvider.GetRequiredService<Microsoft.Extensions.Options.IOptions<RfidBridgeOptions>>();
    return RfidProviderFactory.Create(serviceProvider, options);
});
builder.Services.AddSingleton<RfidSessionService>();

var app = builder.Build();

app.MapGet("/health", () => Results.Ok(new { status = "ok", service = "rfid-bridge" }));

app.MapGet("/rfid/config", (RfidSessionService service) =>
{
    return Results.Ok(service.GetConfiguration());
});

app.MapPost("/rfid/start", async (
    RfidStartRequest request,
    RfidSessionService service,
    CancellationToken cancellationToken) =>
{
    var state = await service.StartAsync(request, cancellationToken);
    return Results.Ok(state);
});

app.MapPost("/rfid/stop", async (RfidSessionService service, CancellationToken cancellationToken) =>
{
    var state = await service.StopAsync(cancellationToken);
    return Results.Ok(state);
});

app.MapPost("/rfid/reset", async (
    RfidStartRequest request,
    RfidSessionService service,
    CancellationToken cancellationToken) =>
{
    var state = await service.ResetAsync(request, cancellationToken);
    return Results.Ok(state);
});

app.MapGet("/rfid/tags", (RfidSessionService service) =>
{
    return Results.Ok(service.GetSnapshot());
});

app.MapGet("/rfid/events", async (HttpContext httpContext, RfidSessionService service, CancellationToken cancellationToken) =>
{
    httpContext.Response.Headers.Append("Cache-Control", "no-cache");
    httpContext.Response.Headers.Append("Content-Type", "text/event-stream");

    var channel = service.Subscribe();
    try
    {
        await foreach (var evt in channel.ReadAllAsync(cancellationToken))
        {
            var payload = JsonSerializer.Serialize(evt);
            await httpContext.Response.WriteAsync($"event: {evt.Type}\n", cancellationToken);
            await httpContext.Response.WriteAsync($"data: {payload}\n\n", cancellationToken);
            await httpContext.Response.Body.FlushAsync(cancellationToken);
        }
    }
    finally
    {
        service.Unsubscribe(channel);
    }
});

app.MapPost("/rfid/mock/tags", async (
    MockTagsRequest request,
    IRfidProvider provider,
    RfidSessionService service,
    CancellationToken cancellationToken) =>
{
    if (provider is not FakeRfidProvider fakeProvider)
    {
        return Results.BadRequest(new { detail = "Mock endpoint is only available with the fake provider." });
    }

    await fakeProvider.PublishTagsAsync(request.Tags, cancellationToken);
    return Results.Ok(service.GetSnapshot());
});

app.Run();
