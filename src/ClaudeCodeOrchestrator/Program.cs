using ClaudeCodeOrchestrator.Data;
using ClaudeCodeOrchestrator.Models;
using ClaudeCodeOrchestrator.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Spectre.Console;

var configuration = new ConfigurationBuilder()
    .SetBasePath(AppContext.BaseDirectory)
    .AddJsonFile("appsettings.json", optional: false, reloadOnChange: false)
    .Build();

var connectionString = configuration.GetConnectionString("Default")!;
var orchestratorConfig = configuration.GetSection("Orchestrator");

// ── Parse CLI args ──────────────────────────────────────────────────────────
string planFile = "todos.json";
int phase = 1;
int step = 1;
bool dryRun = false;
bool forceReload = false;
bool listMode = false;
bool progressMode = false;
double maxBudget = orchestratorConfig.GetValue<double>("MaxBudgetUsd");

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
        case "--reload":
            forceReload = true; break;
        case "--list":
            listMode = true; break;
        case "--progress":
            progressMode = true; break;
        case "--budget" or "-b" when i + 1 < args.Length:
            maxBudget = double.Parse(args[++i]); break;
    }
}

// ── Setup EF Core ───────────────────────────────────────────────────────────
var optionsBuilder = new DbContextOptionsBuilder<OrchestratorDbContext>();
optionsBuilder.UseSqlServer(connectionString);

using var db = new OrchestratorDbContext(optionsBuilder.Options);
await db.Database.MigrateAsync();

// ── Load plan ───────────────────────────────────────────────────────────────
var loader = new PlanLoader(db);
var plan = await loader.LoadOrGetPlanAsync(planFile, forceReload);

// ── --list mode ────────────────────────────────────────────────────────────
if (listMode)
{
    var listTable = new Table()
        .Title("[bold]Plan Steps[/]")
        .Border(TableBorder.Rounded)
        .AddColumn("Phase")
        .AddColumn("Step")
        .AddColumn("Name")
        .AddColumn("Title")
        .AddColumn("Prompt");

    foreach (var s in plan.Steps.OrderBy(s => s.Phase).ThenBy(s => s.SortOrder))
    {
        var prompt = s.Prompt.Length > 80 ? s.Prompt[..80] + "..." : s.Prompt;
        prompt = prompt.ReplaceLineEndings(" ");
        listTable.AddRow(
            new Text(s.Phase.ToString()),
            new Text(s.Step.ToString()),
            new Text(s.Name),
            new Text(s.Title),
            new Text(prompt));
    }

    AnsiConsole.Write(listTable);
    return 0;
}

var projectRoot = plan.ProjectRoot ?? Directory.GetCurrentDirectory();
var logDir = Path.Combine(projectRoot, ".claude", "logs");

// ── Wire up services ────────────────────────────────────────────────────────
var buildCommand = orchestratorConfig.GetValue<string>("BuildCommand") ?? "dotnet build";
var maxTurns = orchestratorConfig.GetValue<int>("MaxTurns");
var allowedTools = orchestratorConfig.GetValue<string>("AllowedTools") ?? "Read Write Edit Bash Glob Grep";

var buildChecker = new BuildChecker(buildCommand);
var agentRunner = new AgentRunner(db, logDir, maxBudget, maxTurns, allowedTools);
var orchestrator = new Orchestrator(db, agentRunner, buildChecker, projectRoot, logDir);

// ── --progress mode ────────────────────────────────────────────────────────
if (progressMode)
{
    var prog = await orchestrator.GetProgressAsync(plan.Id);
    var progressTable = new Table()
        .Title("[bold]Progress[/]")
        .Border(TableBorder.Rounded)
        .AddColumn("Phase")
        .AddColumn("Step")
        .AddColumn("Name")
        .AddColumn("Status")
        .AddColumn("Attempts")
        .AddColumn("Duration")
        .AddColumn("Files");

    foreach (var p in prog.Phases)
    {
        foreach (var s in p.Steps)
        {
            var statusColor = s.Status switch
            {
                AgentStatus.Succeeded => "green",
                AgentStatus.Failed => "red",
                AgentStatus.Running => "yellow",
                AgentStatus.BuildCheck or AgentStatus.Fixing => "yellow",
                AgentStatus.Cancelled => "grey",
                _ => "dim"
            };
            var dur = s.Duration.HasValue ? $"{s.Duration.Value.TotalSeconds:F0}s" : "-";
            var files = s.FilesChanged > 0 ? s.FilesChanged.ToString() : "-";
            progressTable.AddRow(
                new Text(p.Phase.ToString()),
                new Text(s.Step.ToString()),
                new Text(s.Name),
                new Markup($"[{statusColor}]{s.Status}[/]"),
                new Text(s.AttemptCount.ToString()),
                new Text(dur),
                new Text(files));
        }
    }

    AnsiConsole.Write(progressTable);
    return 0;
}

// ── Execute ─────────────────────────────────────────────────────────────────
var bannerPanel = new Panel(
    $"[bold]{Markup.Escape(plan.Name)}[/] ({plan.Steps.Count} steps total)\n" +
    $"Phase [cyan]{phase}[/] | Start at step [cyan]{step}[/] | Budget: [green]${maxBudget}[/]/step | DryRun: {dryRun}")
{
    Border = BoxBorder.Rounded,
    Header = new PanelHeader("[bold blue] Orchestrator [/]"),
    Padding = new Padding(2, 1)
};
AnsiConsole.Write(bannerPanel);
AnsiConsole.WriteLine();

var result = await AnsiConsole.Status().StartAsync("Initializing...", async ctx =>
{
    ctx.Spinner(Spinner.Known.Dots);
    ctx.SpinnerStyle(Style.Parse("cyan"));

    agentRunner.OnOutput += (run, line) =>
    {
        var truncated = line.Length > 120 ? line[..120] + "..." : line;
        ctx.Status(Markup.Escape(truncated));
    };

    agentRunner.OnStatusChanged += (run, status) =>
    {
        var name = run.PlanStep?.Name ?? run.PlanStepId.ToString();
        ctx.Status($"Agent [bold]{Markup.Escape(name)}[/]: {status}");
    };

    orchestrator.OnStepStarted += (planStep, run) =>
    {
        var title = Markup.Escape(planStep.Title);
        var total = plan.Steps.Count(s => s.Phase == planStep.Phase);
        ctx.Status($"[bold cyan]Phase {planStep.Phase} | Step {planStep.Step}/{total} | {title}[/]");
    };

    orchestrator.OnStepCompleted += (planStep, run) =>
    {
        var name = Markup.Escape(planStep.Name);
        ctx.Status($"[green]✓ Step {planStep.Step} ({name}) completed[/]");
    };

    orchestrator.OnStepFailed += (planStep, run) =>
    {
        var name = Markup.Escape(planStep.Name);
        var error = Markup.Escape(run.ErrorMessage ?? "unknown error");
        ctx.Status($"[bold red]✗ Step {planStep.Step} ({name}): {error}[/]");
    };

    orchestrator.OnBuildCheckStarted += (stepName) =>
    {
        ctx.Status($"[yellow]Checking build after {Markup.Escape(stepName)}...[/]");
    };

    orchestrator.OnBuildCheckCompleted += (success, output) =>
    {
        ctx.Status(success ? "[green]Build OK[/]" : "[red]Build FAILED[/]");
    };

    orchestrator.OnInfo += (msg) =>
    {
        ctx.Status($"[dim]{Markup.Escape(msg)}[/]");
    };

    return await orchestrator.ExecutePhaseAsync(plan, phase, step, dryRun);
});

AnsiConsole.WriteLine();
if (result.Success)
    AnsiConsole.MarkupLine($"[green]Phase {phase} completed: {result.CompletedSteps}/{result.TotalSteps} steps.[/]");
else
{
    AnsiConsole.MarkupLine($"[bold red]Phase {phase} failed at step {result.FailedAtStep}: {Markup.Escape(result.Message)}[/]");
    AnsiConsole.MarkupLine($"[yellow]Resume with: dotnet run -- --phase {phase} --step {result.FailedAtStep}[/]");
}

// ── Show progress summary ───────────────────────────────────────────────────
var progress = await orchestrator.GetProgressAsync(plan.Id);
AnsiConsole.WriteLine();

var table = new Table()
    .Title("[bold]Progress Summary[/]")
    .Border(TableBorder.Rounded)
    .AddColumn("Status")
    .AddColumn("Step")
    .AddColumn("Title")
    .AddColumn("Duration")
    .AddColumn("Files Changed");

foreach (var p in progress.Phases)
{
    table.AddRow(new Text($"Phase {p.Phase}", new Style(Color.Cyan1)));
    table.AddEmptyRow();
    foreach (var s in p.Steps)
    {
        var statusColor = s.Status switch
        {
            AgentStatus.Succeeded => "green",
            AgentStatus.Failed => "red",
            AgentStatus.Running => "yellow",
            AgentStatus.BuildCheck or AgentStatus.Fixing => "yellow",
            AgentStatus.Cancelled => "grey",
            _ => "dim"
        };
        var dur = s.Duration.HasValue ? $"{s.Duration.Value.TotalSeconds:F0}s" : "-";
        var files = s.FilesChanged > 0 ? s.FilesChanged.ToString() : "-";
        table.AddRow(
            new Markup($"[{statusColor}]{s.Status}[/]"),
            new Text(s.Step.ToString()),
            new Text(s.Title),
            new Text(dur),
            new Text(files));
    }
}

AnsiConsole.Write(table);

return result.Success ? 0 : 1;
