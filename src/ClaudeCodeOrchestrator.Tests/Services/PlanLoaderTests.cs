using ClaudeCodeOrchestrator.Data;
using ClaudeCodeOrchestrator.Services;
using Microsoft.EntityFrameworkCore;
using Xunit;

namespace ClaudeCodeOrchestrator.Tests.Services;

public class PlanLoaderTests : IDisposable
{
    private readonly OrchestratorDbContext _db;
    private readonly string _tempDir;

    public PlanLoaderTests()
    {
        var options = new DbContextOptionsBuilder<OrchestratorDbContext>()
            .UseInMemoryDatabase(databaseName: Guid.NewGuid().ToString())
            .Options;
        _db = new OrchestratorDbContext(options);
        _tempDir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        _db.Dispose();
        if (Directory.Exists(_tempDir))
            Directory.Delete(_tempDir, recursive: true);
    }

    private string WriteTodosJson(string json)
    {
        var path = Path.Combine(_tempDir, "todos.json");
        File.WriteAllText(path, json);
        return path;
    }

    [Fact]
    public async Task LoadOrGetPlanAsync_DeserializesTodosJson_IntoSteps()
    {
        var json = """
        [
            { "phase": 1, "name": "step-a", "title": "Step A", "prompt": "Do A" },
            { "phase": 1, "name": "step-b", "title": "Step B", "prompt": "Do B" },
            { "phase": 2, "name": "step-c", "title": "Step C", "prompt": "Do C" }
        ]
        """;
        var path = WriteTodosJson(json);
        var loader = new PlanLoader(_db);

        var plan = await loader.LoadOrGetPlanAsync(path);

        Assert.Equal("todos", plan.Name);
        Assert.Equal(3, plan.Steps.Count);

        var phase1 = plan.Steps.Where(s => s.Phase == 1).OrderBy(s => s.Step).ToList();
        Assert.Equal(2, phase1.Count);
        Assert.Equal("step-a", phase1[0].Name);
        Assert.Equal("Step A", phase1[0].Title);
        Assert.Equal("Do A", phase1[0].Prompt);
        Assert.Equal(1, phase1[0].Step);
        Assert.Equal("step-b", phase1[1].Name);
        Assert.Equal(2, phase1[1].Step);

        var phase2 = plan.Steps.Where(s => s.Phase == 2).ToList();
        Assert.Single(phase2);
        Assert.Equal("step-c", phase2[0].Name);
    }

    [Fact]
    public async Task LoadOrGetPlanAsync_ReturnsCachedPlan_OnSecondCall()
    {
        var json = """[{ "phase": 1, "name": "s1", "title": "S1", "prompt": "P1" }]""";
        var path = WriteTodosJson(json);
        var loader = new PlanLoader(_db);

        var plan1 = await loader.LoadOrGetPlanAsync(path);
        var plan2 = await loader.LoadOrGetPlanAsync(path);

        Assert.Equal(plan1.Id, plan2.Id);
    }

    [Fact]
    public async Task LoadOrGetPlanAsync_ForceReload_CreatesNewPlan()
    {
        var json = """[{ "phase": 1, "name": "s1", "title": "S1", "prompt": "P1" }]""";
        var path = WriteTodosJson(json);
        var loader = new PlanLoader(_db);

        var plan1 = await loader.LoadOrGetPlanAsync(path);
        var plan2 = await loader.LoadOrGetPlanAsync(path, forceReload: true);

        Assert.NotEqual(plan1.Id, plan2.Id);
        Assert.Single(plan2.Steps);
    }
}
