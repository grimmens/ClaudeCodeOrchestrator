using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace ClaudeCodeOrchestrator.Data;

/// <summary>
/// Design-time factory for EF Core migrations (dotnet ef migrations add ...).
/// </summary>
public class OrchestratorDbContextFactory : IDesignTimeDbContextFactory<OrchestratorDbContext>
{
    public OrchestratorDbContext CreateDbContext(string[] args)
    {
        var optionsBuilder = new DbContextOptionsBuilder<OrchestratorDbContext>();
        optionsBuilder.UseSqlServer(
            "Server=.;Database=ClaudeCodeOrchestrator;Trusted_Connection=True;TrustServerCertificate=True;");

        return new OrchestratorDbContext(optionsBuilder.Options);
    }
}
