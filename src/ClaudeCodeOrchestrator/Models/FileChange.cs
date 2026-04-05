using System.ComponentModel.DataAnnotations;

namespace ClaudeCodeOrchestrator.Models;

public class FileChange
{
    [Key]
    public Guid Id { get; set; } = Guid.NewGuid();

    public Guid AgentRunId { get; set; }
    public AgentRun AgentRun { get; set; } = null!;

    [MaxLength(500)]
    public string FilePath { get; set; } = string.Empty;

    [MaxLength(20)]
    public string ChangeType { get; set; } = string.Empty; // Added, Modified, Deleted
}
