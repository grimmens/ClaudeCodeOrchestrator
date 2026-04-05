using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;
using Microsoft.Extensions.Configuration;

namespace ClaudeCodeOrchestrator.Data;

/// <summary>
/// Design-time factory for EF Core migrations (dotnet ef migrations add ...).
/// </summary>
public class OrchestratorDbContextFactory : IDesignTimeDbContextFactory<OrchestratorDbContext>
{
    public OrchestratorDbContext CreateDbContext(string[] args)
    {
        var configuration = new ConfigurationBuilder()
            .SetBasePath(AppContext.BaseDirectory)
            .AddJsonFile("appsettings.json", optional: false, reloadOnChange: false)
            .Build();

        var optionsBuilder = new DbContextOptionsBuilder<OrchestratorDbContext>();
        optionsBuilder.UseSqlServer(configuration.GetConnectionString("Default"));

        return new OrchestratorDbContext(optionsBuilder.Options);
    }
}
