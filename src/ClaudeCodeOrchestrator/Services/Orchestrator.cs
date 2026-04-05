using ClaudeCodeOrchestrator.Data;
using ClaudeCodeOrchestrator.Models;
using Microsoft.EntityFrameworkCore;

namespace ClaudeCodeOrchestrator.Services;

/// <summary>
/// Coordinates the execution of plan steps: ordering, dispatching to AgentRunner,
/// build checks, auto-fix retries, and progress tracking.
/// </summary>
public class Orchestrator
{
    private readonly OrchestratorDbContext _db;
    private readonly AgentRunner _agentRunner;
    private readonly BuildChecker _buildChecker;
    private readonly string _projectRoot;
    private readonly string _logDir;

    public event Action<PlanStep, AgentRun>? OnStepStarted;
    public event Action<PlanStep, AgentRun>? OnStepCompleted;
    public event Action<PlanStep, AgentRun>? OnStepFailed;
    public event Action<string>? OnBuildCheckStarted;
    public event Action<bool, string>? OnBuildCheckCompleted;
    public event Action<string>? OnInfo;

    public Orchestrator(
        OrchestratorDbContext db,
        AgentRunner agentRunner,
        BuildChecker buildChecker,
        string projectRoot,
        string logDir)
    {
        _db = db;
        _agentRunner = agentRunner;
        _buildChecker = buildChecker;
        _projectRoot = projectRoot;
        _logDir = logDir;
    }

    /// <summary>
    /// Execute a phase (or all remaining steps from a starting point).
    /// </summary>
    public async Task<OrchestratorResult> ExecutePhaseAsync(
        Plan plan, int phase, int startStep = 1, bool dryRun = false, string? contextPreamble = null, CancellationToken ct = default)
    {
        var steps = plan.Steps
            .Where(s => s.Phase == phase)
            .OrderBy(s => s.SortOrder)
            .ToList();

        if (steps.Count == 0)
            return new OrchestratorResult { Success = false, Message = $"No steps found for phase {phase}" };

        var stepsToRun = steps.Where(s => s.Step >= startStep).ToList();
        var result = new OrchestratorResult { TotalSteps = stepsToRun.Count };

        foreach (var step in stepsToRun)
        {
            ct.ThrowIfCancellationRequested();

            if (dryRun)
            {
                OnInfo?.Invoke($"[DRY RUN] Phase {step.Phase} Step {step.Step}: {step.Title}");
                OnInfo?.Invoke(step.Prompt);
                result.CompletedSteps++;
                continue;
            }

            // Run the agent
            var run = await _agentRunner.RunStepAsync(step, _projectRoot, contextPreamble, ct);
            OnStepStarted?.Invoke(step, run);

            if (run.Status == AgentStatus.Failed)
            {
                OnStepFailed?.Invoke(step, run);
                result.Success = false;
                result.Message = $"Step {step.Step} ({step.Name}) failed: {run.ErrorMessage}";
                result.FailedAtStep = step.Step;
                return result;
            }

            // Build check
            OnBuildCheckStarted?.Invoke(step.Name);
            var (buildOk, buildOutput) = await _buildChecker.CheckBuildAsync(_projectRoot, ct);
            OnBuildCheckCompleted?.Invoke(buildOk, buildOutput);

            if (!buildOk)
            {
                // Auto-fix attempt
                OnInfo?.Invoke("Build failed — attempting auto-fix...");
                run.Status = AgentStatus.Fixing;
                await _db.SaveChangesAsync(ct);

                var fixStep = new PlanStep
                {
                    Phase = step.Phase,
                    Step = step.Step,
                    Name = $"{step.Name}_fix",
                    Title = $"Auto-fix for {step.Title}",
                    Prompt = "The build failed. Run the build command, read the errors, and fix all compile errors. Commit the fix.",
                    PlanId = plan.Id
                };

                var fixRun = await _agentRunner.RunStepAsync(fixStep, _projectRoot, contextPreamble, ct);

                var (fixBuildOk, fixBuildOutput) = await _buildChecker.CheckBuildAsync(_projectRoot, ct);
                OnBuildCheckCompleted?.Invoke(fixBuildOk, fixBuildOutput);

                if (!fixBuildOk)
                {
                    OnStepFailed?.Invoke(step, fixRun);
                    result.Success = false;
                    result.Message = $"Auto-fix for step {step.Step} ({step.Name}) also failed.";
                    result.FailedAtStep = step.Step;
                    return result;
                }
            }

            OnStepCompleted?.Invoke(step, run);
            result.CompletedSteps++;
        }

        result.Success = true;
        result.Message = $"Phase {phase} completed successfully ({result.CompletedSteps}/{result.TotalSteps} steps).";
        return result;
    }

    /// <summary>
    /// Reorder a step within its phase.
    /// </summary>
    public async Task ReorderStepAsync(Guid planId, int phase, int fromStep, int toStep, CancellationToken ct = default)
    {
        var steps = await _db.PlanSteps
            .Where(s => s.PlanId == planId && s.Phase == phase)
            .OrderBy(s => s.SortOrder)
            .ToListAsync(ct);

        if (fromStep < 1 || fromStep > steps.Count || toStep < 1 || toStep > steps.Count)
            throw new ArgumentException("Step number out of range");

        var moving = steps[fromStep - 1];
        steps.RemoveAt(fromStep - 1);
        steps.Insert(toStep - 1, moving);

        for (int i = 0; i < steps.Count; i++)
        {
            steps[i].SortOrder = i;
            steps[i].Step = i + 1;
        }

        await _db.SaveChangesAsync(ct);
    }

    /// <summary>
    /// Get the current progress snapshot for a plan.
    /// </summary>
    public async Task<PlanProgress> GetProgressAsync(Guid planId, CancellationToken ct = default)
    {
        var plan = await _db.Plans
            .Include(p => p.Steps)
                .ThenInclude(s => s.AgentRuns)
            .FirstOrDefaultAsync(p => p.Id == planId, ct);

        if (plan is null)
            return new PlanProgress();

        var progress = new PlanProgress { PlanName = plan.Name };

        foreach (var phaseGroup in plan.Steps.GroupBy(s => s.Phase).OrderBy(g => g.Key))
        {
            var phaseProgress = new PhaseProgress { Phase = phaseGroup.Key };

            foreach (var step in phaseGroup.OrderBy(s => s.SortOrder))
            {
                var latestRun = step.AgentRuns.MaxBy(r => r.CreatedAt);
                phaseProgress.Steps.Add(new StepProgress
                {
                    Step = step.Step,
                    Name = step.Name,
                    Title = step.Title,
                    Status = latestRun?.Status ?? AgentStatus.Pending,
                    AttemptCount = step.AgentRuns.Count,
                    Duration = latestRun?.FinishedAt - latestRun?.StartedAt,
                    FilesChanged = latestRun?.FilesChanged.Count ?? 0
                });
            }

            progress.Phases.Add(phaseProgress);
        }

        return progress;
    }
}

public class OrchestratorResult
{
    public bool Success { get; set; }
    public string Message { get; set; } = string.Empty;
    public int TotalSteps { get; set; }
    public int CompletedSteps { get; set; }
    public int? FailedAtStep { get; set; }
}

public class PlanProgress
{
    public string PlanName { get; set; } = string.Empty;
    public List<PhaseProgress> Phases { get; set; } = new();
}

public class PhaseProgress
{
    public int Phase { get; set; }
    public List<StepProgress> Steps { get; set; } = new();
}

public class StepProgress
{
    public int Step { get; set; }
    public string Name { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public AgentStatus Status { get; set; }
    public int AttemptCount { get; set; }
    public TimeSpan? Duration { get; set; }
    public int FilesChanged { get; set; }
}
