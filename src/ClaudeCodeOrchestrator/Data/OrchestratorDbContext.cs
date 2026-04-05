using ClaudeCodeOrchestrator.Models;
using Microsoft.EntityFrameworkCore;

namespace ClaudeCodeOrchestrator.Data;

public class OrchestratorDbContext : DbContext
{
    public OrchestratorDbContext(DbContextOptions<OrchestratorDbContext> options)
        : base(options) { }

    public DbSet<Plan> Plans => Set<Plan>();
    public DbSet<PlanStep> PlanSteps => Set<PlanStep>();
    public DbSet<AgentRun> AgentRuns => Set<AgentRun>();
    public DbSet<FileChange> FileChanges => Set<FileChange>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Plan>(entity =>
        {
            entity.HasIndex(e => e.Name);
        });

        modelBuilder.Entity<PlanStep>(entity =>
        {
            entity.HasIndex(e => new { e.PlanId, e.Phase, e.Step }).IsUnique();
            entity.HasIndex(e => new { e.PlanId, e.SortOrder });

            entity.HasOne(e => e.Plan)
                .WithMany(p => p.Steps)
                .HasForeignKey(e => e.PlanId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        modelBuilder.Entity<AgentRun>(entity =>
        {
            entity.HasIndex(e => e.Status);
            entity.HasIndex(e => e.CreatedAt);

            entity.HasOne(e => e.PlanStep)
                .WithMany(s => s.AgentRuns)
                .HasForeignKey(e => e.PlanStepId)
                .OnDelete(DeleteBehavior.Cascade);

            entity.Property(e => e.CostUsd).HasColumnType("decimal(10,4)");
        });

        modelBuilder.Entity<FileChange>(entity =>
        {
            entity.HasOne(e => e.AgentRun)
                .WithMany(r => r.FilesChanged)
                .HasForeignKey(e => e.AgentRunId)
                .OnDelete(DeleteBehavior.Cascade);
        });
    }
}
