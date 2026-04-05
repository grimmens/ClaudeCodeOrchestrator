using ClaudeCodeOrchestrator.Services;
using Xunit;

namespace ClaudeCodeOrchestrator.Tests.Services;

public class BuildCheckerTests
{
    [Fact]
    public void BuildChecker_CanBeConstructed()
    {
        var checker = new BuildChecker("dotnet --version");
        Assert.NotNull(checker);
    }

    [Fact]
    public async Task CheckBuildAsync_RunsDotnetVersion_WithoutCrashing()
    {
        var checker = new BuildChecker("dotnet --version");
        var projectRoot = Directory.GetCurrentDirectory();

        var (success, output) = await checker.CheckBuildAsync(projectRoot);

        Assert.True(success);
        Assert.False(string.IsNullOrWhiteSpace(output));
    }
}
