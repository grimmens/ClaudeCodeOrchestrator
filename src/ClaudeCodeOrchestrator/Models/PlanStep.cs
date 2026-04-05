using System.ComponentModel.DataAnnotations;

namespace ClaudeCodeOrchestrator.Models;

public class PlanStep
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    public int Phase { get; set; }
    public int Step { get; set; }

    [MaxLength(100)]
    public string Name { get; set; } = string.Empty;

    [MaxLength(200)]
    public string Title { get; set; } = string.Empty;

    public string Prompt { get; set; } = string.Empty;

    public int SortOrder { get; set; }

    public Guid PlanId { get; set; }
    public Plan Plan { get; set; } = null!;

    public ICollection<AgentRun> AgentRuns { get; set; } = new List<AgentRun>();
}
