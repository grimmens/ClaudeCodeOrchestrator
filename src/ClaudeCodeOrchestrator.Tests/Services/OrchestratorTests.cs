using ClaudeCodeOrchestrator.Data;
using ClaudeCodeOrchestrator.Models;
using ClaudeCodeOrchestrator.Services;
using Microsoft.EntityFrameworkCore;
using Xunit;

namespace ClaudeCodeOrchestrator.Tests.Services;

/// <summary>
/// Fake agent runner that returns configurable results without spawning processes.
/// </summary>
public class FakeAgentRunner : IAgentRunner
{
    public event Action<AgentRun, string>? OnOutput;
    public event Action<AgentRun, AgentStatus>? OnStatusChanged;

    public List<PlanStep> ExecutedSteps { get; } = new();
    public AgentStatus ResultStatus { get; set; } = AgentStatus.Succeeded;

    public Task<AgentRun> RunStepAsync(PlanStep step, string projectRoot, string? contextPreamble = null, CancellationToken ct = default)
    {
        ExecutedSteps.Add(step);

        var run = new AgentRun
        {
            PlanStepId = step.Id,
            Status = ResultStatus,
            StartedAt = DateTime.UtcNow,
            FinishedAt = DateTime.UtcNow,
            ExitCode = ResultStatus == AgentStatus.Succeeded ? 0 : 1,
            ErrorMessage = ResultStatus == AgentStatus.Failed ? "Simulated failure" : null
        };

        OnStatusChanged?.Invoke(run, run.Status);
        return Task.FromResult(run);
    }
}

public class OrchestratorTests : IDisposable
{
    private readonly OrchestratorDbContext _db;
    private readonly FakeAgentRunner _fakeRunner;
    private readonly string _tempDir;

    public OrchestratorTests()
    {
        var options = new DbContextOptionsBuilder<OrchestratorDbContext>()
            .UseInMemoryDatabase(databaseName: Guid.NewGuid().ToString())
            .Options;
        _db = new OrchestratorDbContext(options);
        _fakeRunner = new FakeAgentRunner();
        _tempDir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        _db.Dispose();
        if (Directory.Exists(_tempDir))
            Directory.Delete(_tempDir, recursive: true);
    }

    private (Plan plan, Orchestrator orchestrator) CreateTestSetup(int stepCount = 2)
    {
        var plan = new Plan { Name = "test-plan" };
        for (int i = 1; i <= stepCount; i++)
        {
            plan.Steps.Add(new PlanStep
            {
                Phase = 1,
                Step = i,
                Name = $"step-{i}",
                Title = $"Step {i}",
                Prompt = $"Do step {i}",
                SortOrder = i - 1,
                PlanId = plan.Id
            });
        }

        _db.Plans.Add(plan);
        _db.SaveChanges();

        var buildChecker = new BuildChecker("dotnet --version");
        var orchestrator = new Orchestrator(_db, _fakeRunner, buildChecker, _tempDir, _tempDir);

        return (plan, orchestrator);
    }

    [Fact]
    public async Task DryRun_ReturnsSuccess_WithoutExecutingSteps()
    {
        var (plan, orchestrator) = CreateTestSetup();

        var result = await orchestrator.ExecutePhaseAsync(plan, phase: 1, dryRun: true);

        Assert.True(result.Success);
        Assert.Equal(2, result.CompletedSteps);
        Assert.Empty(_fakeRunner.ExecutedSteps);
    }

    [Fact]
    public async Task ExecutePhaseAsync_RunsStepsInOrder()
    {
        var (plan, orchestrator) = CreateTestSetup(stepCount: 3);

        var result = await orchestrator.ExecutePhaseAsync(plan, phase: 1);

        Assert.True(result.Success);
        Assert.Equal(3, result.CompletedSteps);
        Assert.Equal(3, _fakeRunner.ExecutedSteps.Count);
        Assert.Equal("step-1", _fakeRunner.ExecutedSteps[0].Name);
        Assert.Equal("step-2", _fakeRunner.ExecutedSteps[1].Name);
        Assert.Equal("step-3", _fakeRunner.ExecutedSteps[2].Name);
    }

    [Fact]
    public async Task ExecutePhaseAsync_BuildFailure_TriggersAutoFix()
    {
        var plan = new Plan { Name = "test-plan" };
        plan.Steps.Add(new PlanStep
        {
            Phase = 1,
            Step = 1,
            Name = "step-1",
            Title = "Step 1",
            Prompt = "Do step 1",
            SortOrder = 0,
            PlanId = plan.Id
        });

        _db.Plans.Add(plan);
        _db.SaveChanges();

        // Use a build command that will always fail
        var failingBuildChecker = new BuildChecker("dotnet build --non-existent-flag-that-fails");
        var orchestrator = new Orchestrator(_db, _fakeRunner, failingBuildChecker, _tempDir, _tempDir);

        var result = await orchestrator.ExecutePhaseAsync(plan, phase: 1);

        // The build will fail, then auto-fix will also fail (build still fails) => overall failure
        Assert.False(result.Success);
        Assert.Equal(1, result.FailedAtStep);
        // Should have executed original step + fix step
        Assert.Equal(2, _fakeRunner.ExecutedSteps.Count);
        Assert.Contains("_fix", _fakeRunner.ExecutedSteps[1].Name);
    }
}
