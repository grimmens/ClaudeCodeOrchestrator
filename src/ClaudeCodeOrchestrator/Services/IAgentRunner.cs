using ClaudeCodeOrchestrator.Models;

namespace ClaudeCodeOrchestrator.Services;

/// <summary>
/// Abstraction over agent execution, allowing test doubles for Orchestrator testing.
/// </summary>
public interface IAgentRunner
{
    event Action<AgentRun, string>? OnOutput;
    event Action<AgentRun, AgentStatus>? OnStatusChanged;

    Task<AgentRun> RunStepAsync(PlanStep step, string projectRoot, string? contextPreamble = null, CancellationToken ct = default);
}
