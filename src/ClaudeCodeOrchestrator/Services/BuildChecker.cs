using System.Diagnostics;

namespace ClaudeCodeOrchestrator.Services;

/// <summary>
/// Runs dotnet build and returns whether it succeeded.
/// </summary>
public class BuildChecker
{
    public async Task<(bool success, string output)> CheckBuildAsync(string projectRoot, CancellationToken ct = default)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "dotnet",
            Arguments = "build",
            WorkingDirectory = projectRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        using var process = new Process { StartInfo = psi };
        process.Start();

        var stdout = await process.StandardOutput.ReadToEndAsync(ct);
        var stderr = await process.StandardError.ReadToEndAsync(ct);
        await process.WaitForExitAsync(ct);

        var fullOutput = stdout + stderr;
        return (process.ExitCode == 0, fullOutput);
    }
}
