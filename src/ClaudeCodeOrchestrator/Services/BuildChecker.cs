using System.Diagnostics;

namespace ClaudeCodeOrchestrator.Services;

/// <summary>
/// Runs dotnet build and returns whether it succeeded.
/// </summary>
public class BuildChecker
{
    private readonly string _buildCommand;

    public BuildChecker(string buildCommand = "dotnet build")
    {
        _buildCommand = buildCommand;
    }

    public async Task<(bool success, string output)> CheckBuildAsync(string projectRoot, CancellationToken ct = default)
    {
        var parts = _buildCommand.Split(' ', 2);
        var psi = new ProcessStartInfo
        {
            FileName = parts[0],
            Arguments = parts.Length > 1 ? parts[1] : "",
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
