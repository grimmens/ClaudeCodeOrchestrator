using System.Diagnostics;
using System.Text;
using ClaudeCodeOrchestrator.Data;
using ClaudeCodeOrchestrator.Models;

namespace ClaudeCodeOrchestrator.Services;

/// <summary>
/// Spawns a claude CLI subprocess for a given PlanStep and streams output.
/// </summary>
public class AgentRunner : IAgentRunner
{
    private readonly OrchestratorDbContext _db;
    private readonly string _logDir;
    private readonly double _maxBudget;
    private readonly int _maxTurns;
    private readonly string _allowedTools;

    public AgentRunner(OrchestratorDbContext db, string logDir, double maxBudget = 5.00, int maxTurns = 50, string allowedTools = "Read Write Edit Bash Glob Grep")
    {
        _db = db;
        _logDir = logDir;
        _maxBudget = maxBudget;
        _maxTurns = maxTurns;
        _allowedTools = allowedTools;
    }

    public event Action<AgentRun, string>? OnOutput;
    public event Action<AgentRun, AgentStatus>? OnStatusChanged;

    public async Task<AgentRun> RunStepAsync(PlanStep step, string projectRoot, string? contextPreamble = null, CancellationToken ct = default)
    {
        var run = new AgentRun
        {
            PlanStepId = step.Id,
            AttemptNumber = step.AgentRuns.Count + 1,
            Status = AgentStatus.Running,
            StartedAt = DateTime.UtcNow
        };

        _db.AgentRuns.Add(run);
        await _db.SaveChangesAsync(ct);

        OnStatusChanged?.Invoke(run, AgentStatus.Running);

        var prompt = BuildPrompt(step, contextPreamble);
        var logFile = Path.Combine(_logDir, $"{DateTime.Now:yyyy-MM-dd_HH-mm-ss}_{step.Name}.log");
        run.LogPath = logFile;

        Directory.CreateDirectory(_logDir);

        try
        {
            var (exitCode, output) = await RunClaudeProcessAsync(prompt, projectRoot, logFile, run, ct);

            run.ExitCode = exitCode;
            run.Output = output;
            run.Status = exitCode == 0 ? AgentStatus.Succeeded : AgentStatus.Failed;
            run.FinishedAt = DateTime.UtcNow;

            if (exitCode != 0)
            {
                run.ErrorMessage = $"Claude exited with code {exitCode}";
            }

            // Capture git changes made during this run
            await CaptureFileChangesAsync(run, projectRoot, ct);
        }
        catch (OperationCanceledException)
        {
            run.Status = AgentStatus.Cancelled;
            run.FinishedAt = DateTime.UtcNow;
            run.ErrorMessage = "Cancelled by user";
        }
        catch (Exception ex)
        {
            run.Status = AgentStatus.Failed;
            run.FinishedAt = DateTime.UtcNow;
            run.ErrorMessage = ex.Message;
        }

        OnStatusChanged?.Invoke(run, run.Status);
        await _db.SaveChangesAsync(ct);

        return run;
    }

    private string BuildPrompt(PlanStep step, string? contextPreamble)
    {
        var sb = new StringBuilder();

        if (!string.IsNullOrEmpty(contextPreamble))
        {
            sb.AppendLine(contextPreamble);
            sb.AppendLine();
        }

        sb.AppendLine("IMPORTANT:");
        sb.AppendLine("- Work ONLY on the step described below, nothing more.");
        sb.AppendLine("- Make sure the build passes when you are done.");
        sb.AppendLine("- Commit your changes with a descriptive commit message.");
        sb.AppendLine("- If you encounter problems, fix them independently.");
        sb.AppendLine();
        sb.AppendLine("TASK:");
        sb.AppendLine(step.Prompt);

        return sb.ToString();
    }

    private async Task<(int exitCode, string output)> RunClaudeProcessAsync(
        string prompt, string workingDir, string logFile, AgentRun run, CancellationToken ct)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "claude",
            Arguments = $"-p - --allowedTools {_allowedTools} --max-turns {_maxTurns} --max-budget-usd {_maxBudget}",
            WorkingDirectory = workingDir,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        using var process = new Process { StartInfo = psi };
        var outputBuilder = new StringBuilder();

        await using var logWriter = new StreamWriter(logFile, append: false, encoding: Encoding.UTF8);

        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            outputBuilder.AppendLine(e.Data);
            logWriter.WriteLine(e.Data);
            OnOutput?.Invoke(run, e.Data);
        };

        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            outputBuilder.AppendLine(e.Data);
            logWriter.WriteLine($"[STDERR] {e.Data}");
            OnOutput?.Invoke(run, $"[STDERR] {e.Data}");
        };

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        // Write prompt to stdin and close it so claude reads it
        await process.StandardInput.WriteAsync(prompt);
        process.StandardInput.Close();

        await process.WaitForExitAsync(ct);

        return (process.ExitCode, outputBuilder.ToString());
    }

    private async Task CaptureFileChangesAsync(AgentRun run, string projectRoot, CancellationToken ct)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "git",
                Arguments = "diff --name-status HEAD~1 HEAD",
                WorkingDirectory = projectRoot,
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using var process = Process.Start(psi);
            if (process is null) return;

            var output = await process.StandardOutput.ReadToEndAsync(ct);
            await process.WaitForExitAsync(ct);

            if (process.ExitCode != 0) return;

            foreach (var line in output.Split('\n', StringSplitOptions.RemoveEmptyEntries))
            {
                var parts = line.Split('\t', 2);
                if (parts.Length < 2) continue;

                run.FilesChanged.Add(new FileChange
                {
                    FilePath = parts[1].Trim(),
                    ChangeType = parts[0].Trim() switch
                    {
                        "A" => "Added",
                        "M" => "Modified",
                        "D" => "Deleted",
                        _ => parts[0].Trim()
                    }
                });
            }
        }
        catch
        {
            // Non-critical — don't fail the run over git diff issues
        }
    }
}
