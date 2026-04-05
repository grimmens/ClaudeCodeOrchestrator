namespace ClaudeCodeOrchestrator.Models;

/// <summary>
/// Matches the structure of entries in todos.json for deserialization.
/// </summary>
public class TodoJson
{
    public int Phase { get; set; }
    public string Name { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string Prompt { get; set; } = string.Empty;
}
