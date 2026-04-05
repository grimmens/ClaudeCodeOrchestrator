using System.Text.Json;
using ClaudeCodeOrchestrator.Data;
using ClaudeCodeOrchestrator.Models;
using Microsoft.EntityFrameworkCore;

namespace ClaudeCodeOrchestrator.Services;

/// <summary>
/// Loads a todos.json plan file into the database, or returns the existing plan if already imported.
/// </summary>
public class PlanLoader
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly OrchestratorDbContext _db;

    public PlanLoader(OrchestratorDbContext db)
    {
        _db = db;
    }

    public async Task<Plan> LoadOrGetPlanAsync(string planFilePath, bool forceReload = false)
    {
        var fullPath = Path.GetFullPath(planFilePath);

        var existing = await _db.Plans
            .Include(p => p.Steps)
            .FirstOrDefaultAsync(p => p.SourceFile == fullPath);

        if (existing is not null && forceReload)
        {
            _db.PlanSteps.RemoveRange(existing.Steps);
            _db.Plans.Remove(existing);
            await _db.SaveChangesAsync();
            existing = null;
        }

        if (existing is not null)
            return existing;

        var json = await File.ReadAllTextAsync(fullPath);
        var todos = JsonSerializer.Deserialize<List<TodoJson>>(json, JsonOptions)
            ?? throw new InvalidOperationException($"Could not deserialize {fullPath}");

        var plan = new Plan
        {
            Name = Path.GetFileNameWithoutExtension(fullPath),
            SourceFile = fullPath,
            ProjectRoot = Path.GetDirectoryName(fullPath)
        };

        int sortOrder = 0;
        var grouped = todos.GroupBy(t => t.Phase).OrderBy(g => g.Key);

        foreach (var phaseGroup in grouped)
        {
            int stepNum = 1;
            foreach (var todo in phaseGroup)
            {
                plan.Steps.Add(new PlanStep
                {
                    Phase = todo.Phase,
                    Step = stepNum++,
                    Name = todo.Name,
                    Title = todo.Title,
                    Prompt = todo.Prompt,
                    SortOrder = sortOrder++
                });
            }
        }

        _db.Plans.Add(plan);
        await _db.SaveChangesAsync();

        return plan;
    }

    public async Task<Plan?> GetPlanAsync(Guid planId)
    {
        return await _db.Plans
            .Include(p => p.Steps)
                .ThenInclude(s => s.AgentRuns)
                    .ThenInclude(r => r.FilesChanged)
            .FirstOrDefaultAsync(p => p.Id == planId);
    }
}
