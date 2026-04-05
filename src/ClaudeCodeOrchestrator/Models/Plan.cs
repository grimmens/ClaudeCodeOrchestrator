using System.ComponentModel.DataAnnotations;

namespace ClaudeCodeOrchestrator.Models;

public class Plan
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    [MaxLength(200)]
    public string Name { get; set; } = string.Empty;

    [MaxLength(500)]
    public string? SourceFile { get; set; }

    [MaxLength(500)]
    public string? ProjectRoot { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public ICollection<PlanStep> Steps { get; set; } = new List<PlanStep>();
}
