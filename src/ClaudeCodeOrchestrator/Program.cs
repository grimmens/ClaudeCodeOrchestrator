using ClaudeCodeOrchestrator.Data;
using ClaudeCodeOrchestrator.Services;
using Microsoft.EntityFrameworkCore;

const string ConnectionString = "Server=.;Database=ClaudeCodeOrchestrator;Trusted_Connection=True;TrustServerCertificate=True;";

// ── Parse CLI args ──────────────────────────────────────────────────────────
string planFile = "todos.json";
int phase = 1;
int step = 1;
bool dryRun = false;
double maxBudget = 5.00;

for (int i = 0; i < args.Length; i++)
{
    switch (args[i].ToLower())
    {
        case "--plan" or "-p" when i + 1 < args.Length:
            planFile = args[++i]; break;
        case "--phase" when i + 1 < args.Length:
            phase = int.Parse(args[++i]); break;
        case "--step" or "-s" when i + 1 < args.Length:
            step = int.Parse(args[++i]); break;
        case "--dry-run":
            dryRun = true; break;
        case "--budget" or "-b" when i + 1 < args.Length:
            maxBudget = double.Parse(args[++i]); break;
    }
}

// ── Setup EF Core ───────────────────────────────────────────────────────────
var optionsBuilder = new DbContextOptionsBuilder<OrchestratorDbContext>();
optionsBuilder.UseSqlServer(ConnectionString);

using var db = new OrchestratorDbContext(optionsBuilder.Options);
await db.Database.MigrateAsync();

// ── Load plan ───────────────────────────────────────────────────────────────
var loader = new PlanLoader(db);
var plan = await loader.LoadOrGetPlanAsync(planFile);

var projectRoot = plan.ProjectRoot ?? Directory.GetCurrentDirectory();
var logDir = Path.Combine(projectRoot, ".claude", "logs");

// ── Wire up services ────────────────────────────────────────────────────────
var buildChecker = new BuildChecker();
var agentRunner = new AgentRunner(db, logDir, maxBudget);
var orchestrator = new Orchestrator(db, agentRunner, buildChecker, projectRoot, logDir);

// ── Console output hooks (placeholder — UX will be fleshed out next) ────────
agentRunner.OnOutput += (run, line) =>
{
    Console.WriteLine(line);
};

agentRunner.OnStatusChanged += (run, status) =>
{
    Console.WriteLine($"[Agent {run.PlanStep?.Name ?? run.PlanStepId.ToString()}] Status: {status}");
};

orchestrator.OnStepStarted += (planStep, run) =>
{
    Console.WriteLine($"=== Phase {planStep.Phase} | Step {planStep.Step}/{plan.Steps.Count(s => s.Phase == planStep.Phase)} | {planStep.Title} ===");
};

orchestrator.OnStepCompleted += (planStep, run) =>
{
    Console.WriteLine($"[OK] Step {planStep.Step} ({planStep.Name}) completed.");
};

orchestrator.OnStepFailed += (planStep, run) =>
{
    Console.WriteLine($"[FAIL] Step {planStep.Step} ({planStep.Name}): {run.ErrorMessage}");
};

orchestrator.OnBuildCheckStarted += (stepName) =>
{
    Console.WriteLine($"[BUILD] Checking build after {stepName}...");
};

orchestrator.OnBuildCheckCompleted += (success, output) =>
{
    Console.WriteLine(success ? "[BUILD] OK" : $"[BUILD] FAILED\n{output}");
};

orchestrator.OnInfo += (msg) =>
{
    Console.WriteLine($"[INFO] {msg}");
};

// ── Execute ─────────────────────────────────────────────────────────────────
Console.WriteLine($"Plan: {plan.Name} ({plan.Steps.Count} steps total)");
Console.WriteLine($"Phase {phase} | Start at step {step} | Budget: ${maxBudget}/step | DryRun: {dryRun}");
Console.WriteLine();

var result = await orchestrator.ExecutePhaseAsync(plan, phase, step, dryRun);

Console.WriteLine();
Console.WriteLine(result.Success
    ? $"Phase {phase} completed: {result.CompletedSteps}/{result.TotalSteps} steps."
    : $"Phase {phase} failed at step {result.FailedAtStep}: {result.Message}");

if (!result.Success)
{
    Console.WriteLine($"Resume with: dotnet run -- --phase {phase} --step {result.FailedAtStep}");
}

// ── Show progress summary ───────────────────────────────────────────────────
var progress = await orchestrator.GetProgressAsync(plan.Id);
Console.WriteLine();
Console.WriteLine("=== Progress Summary ===");
foreach (var p in progress.Phases)
{
    Console.WriteLine($"Phase {p.Phase}:");
    foreach (var s in p.Steps)
    {
        var dur = s.Duration.HasValue ? $" ({s.Duration.Value.TotalSeconds:F0}s)" : "";
        var files = s.FilesChanged > 0 ? $" [{s.FilesChanged} files]" : "";
        Console.WriteLine($"  [{s.Status,-10}] {s.Step}. {s.Title}{dur}{files}");
    }
}

return result.Success ? 0 : 1;
