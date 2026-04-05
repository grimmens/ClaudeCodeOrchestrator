namespace ClaudeCodeOrchestrator.Models;

public enum AgentStatus
{
    Pending,
    Running,
    BuildCheck,
    Fixing,
    Succeeded,
    Failed,
    Cancelled
}
