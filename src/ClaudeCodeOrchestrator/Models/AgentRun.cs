using System.ComponentModel.DataAnnotations;

namespace ClaudeCodeOrchestrator.Models;

public class AgentRun
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    public Guid PlanStepId { get; set; }
    public PlanStep PlanStep { get; set; } = null!;

    public AgentStatus Status { get; set; } = AgentStatus.Pending;

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? StartedAt { get; set; }
    public DateTime? FinishedAt { get; set; }

    [MaxLength(500)]
    public string? LogPath { get; set; }

    public string? Output { get; set; }
    public string? ErrorMessage { get; set; }

    public int ExitCode { get; set; }
    public int AttemptNumber { get; set; } = 1;
    public decimal? CostUsd { get; set; }

    public ICollection<FileChange> FilesChanged { get; set; } = new List<FileChange>();
}
