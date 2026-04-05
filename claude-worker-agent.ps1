#Requires -Version 7.0
<#
.SYNOPSIS
    ClaudeCodeOrchestrator Worker Agent - Executes plan steps sequentially.

.DESCRIPTION
    Reads steps from a JSON plan file and executes them one by one using Claude Code.
    Each step is run in its own Claude session, build-checked, and committed.
    All output is streamed to the console and logged to files.

.PARAMETER PlanFile
    Path to the JSON file with the steps. Default: todos.json

.PARAMETER Step
    Start execution from this step number (1-based). Default: 1

.PARAMETER DryRun
    Show prompts without executing them.

.PARAMETER MaxBudget
    Max USD budget per step. Default: 5.00

.PARAMETER IncludeContext
    Include results from previous steps in each prompt. Default: true

.EXAMPLE
    .\claude-worker-agent.ps1
    .\claude-worker-agent.ps1 -PlanFile .\other-plan.json
    .\claude-worker-agent.ps1 -Step 3
    .\claude-worker-agent.ps1 -DryRun
#>

param(
    [string]$PlanFile = "todos.json",
    [int]$Step = 1,
    [switch]$DryRun,
    [double]$MaxBudget = 5.00,
    [bool]$IncludeContext = $true
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$LogDir = Join-Path $ProjectRoot ".claude/logs"

# -- Load plan from JSON -------------------------------------------------------
$PlanPath = if ([System.IO.Path]::IsPathRooted($PlanFile)) { $PlanFile } else { Join-Path $ProjectRoot $PlanFile }
if (-not (Test-Path $PlanPath)) {
    Write-Host "Plan file not found: $PlanPath" -ForegroundColor Red
    exit 1
}
$AllSteps = Get-Content $PlanPath -Raw | ConvertFrom-Json

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# -- Results tracker (for context sharing) -------------------------------------
$StepResults = @{}

# -- Helper functions ----------------------------------------------------------

function Write-StepHeader {
    param([int]$StepNum, [int]$Total, [string]$Title)
    $separator = "=" * 70
    Write-Host ""
    Write-Host $separator -ForegroundColor Cyan
    Write-Host "  Step $StepNum/$Total | $Title" -ForegroundColor Cyan
    Write-Host $separator -ForegroundColor Cyan
    Write-Host ""
}

function Build-ContextSection {
    param([int]$CurrentStep)

    if (-not $IncludeContext -or $StepResults.Count -eq 0) { return "" }

    $contextLines = @("CONTEXT FROM PREVIOUS STEPS:")
    foreach ($key in ($StepResults.Keys | Sort-Object)) {
        if ($key -ge $CurrentStep) { continue }
        $prev = $StepResults[$key]
        $result = $prev.Result
        # Truncate long results
        if ($result.Length -gt 500) {
            $result = $result.Substring(0, 500) + "... [truncated]"
        }
        $contextLines += "---"
        $contextLines += "Step $key ($($prev.Name)): $($prev.Title)"
        $contextLines += "Result: $result"
    }
    $contextLines += "---"
    $contextLines += ""
    return ($contextLines -join "`n")
}

function Invoke-Claude {
    param(
        [string]$Prompt,
        [string]$StepName
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $logFile = Join-Path $LogDir "${timestamp}_${StepName}.log"

    if ($DryRun) {
        Write-Host "[DRY RUN] Would execute:" -ForegroundColor Yellow
        Write-Host $Prompt -ForegroundColor Gray
        Write-Host ""
        return @{ Success = $true; Output = "[DRY RUN]" }
    }

    $fullPrompt = @"
IMPORTANT:
- Work ONLY on the step described below, nothing more.
- Make sure 'dotnet build' passes when you are done.
- Commit your changes with a descriptive commit message.
- If you encounter problems, fix them independently.

$Prompt
"@

    $promptFile = Join-Path $env:TEMP "claude-prompt-${timestamp}-${StepName}.md"
    [System.IO.File]::WriteAllText($promptFile, $fullPrompt, [System.Text.Encoding]::UTF8)

    Write-Host "Starting Claude session..." -ForegroundColor Green
    Write-Host "Log:    $logFile" -ForegroundColor DarkGray
    Write-Host ""

    try {
        $psi = [System.Diagnostics.ProcessStartInfo]::new()
        $psi.FileName = "claude"
        $psi.Arguments = "-p - --allowedTools Read Write Edit Bash Glob Grep --max-turns 50 --max-budget-usd $MaxBudget --verbose"
        $psi.WorkingDirectory = $ProjectRoot
        $psi.UseShellExecute = $false
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

        $proc = [System.Diagnostics.Process]::new()
        $proc.StartInfo = $psi

        $logLines = [System.Collections.Generic.List[string]]::new()

        $outEvent = Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action {
            if ($null -ne $EventArgs.Data) {
                Write-Host $EventArgs.Data
                $Event.MessageData.Add($EventArgs.Data)
            }
        } -MessageData $logLines

        $errEvent = Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -Action {
            if ($null -ne $EventArgs.Data) {
                Write-Host "[STDERR] $($EventArgs.Data)" -ForegroundColor Red
                $Event.MessageData.Add("[STDERR] $($EventArgs.Data)")
            }
        } -MessageData $logLines

        $proc.Start() | Out-Null
        $proc.BeginOutputReadLine()
        $proc.BeginErrorReadLine()

        $proc.StandardInput.Write($fullPrompt)
        $proc.StandardInput.Close()

        $proc.WaitForExit()
        $exitCode = $proc.ExitCode

        Start-Sleep -Milliseconds 300

        $logLines | Out-File -FilePath $logFile -Encoding utf8

        Unregister-Event -SourceIdentifier $outEvent.Name -ErrorAction SilentlyContinue
        Unregister-Event -SourceIdentifier $errEvent.Name -ErrorAction SilentlyContinue
        Remove-Job -Name $outEvent.Name -Force -ErrorAction SilentlyContinue
        Remove-Job -Name $errEvent.Name -Force -ErrorAction SilentlyContinue
        $proc.Dispose()

        $outputText = $logLines -join "`n"

        Write-Host ""
        if ($exitCode -ne 0) {
            Write-Host "WARNING: Claude exited with code $exitCode" -ForegroundColor Red
            return @{ Success = $false; Output = $outputText }
        }

        Write-Host "Claude session completed successfully." -ForegroundColor Green
        Write-Host ""
        return @{ Success = $true; Output = $outputText }
    }
    catch {
        Write-Host "ERROR: $_" -ForegroundColor Red
        Write-Host $_.ScriptStackTrace -ForegroundColor DarkRed
        return @{ Success = $false; Output = $_.ToString() }
    }
    finally {
        if (Test-Path $promptFile) { Remove-Item $promptFile -Force -ErrorAction SilentlyContinue }
    }
}

function Confirm-BuildSuccess {
    Write-Host "Checking build..." -ForegroundColor Yellow
    $slnFile = Get-ChildItem -Path $ProjectRoot -Filter "*.sln" -Depth 0 -ErrorAction SilentlyContinue | Select-Object -First 1
    $csprojFile = Get-ChildItem -Path $ProjectRoot -Filter "*.csproj" -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
    $buildTarget = if ($slnFile) { $slnFile.FullName } elseif ($csprojFile) { $csprojFile.FullName } else { $null }

    if (-not $buildTarget) {
        Write-Host "No .sln or .csproj found - skipping build check." -ForegroundColor Yellow
        return $true
    }

    Write-Host "Building: $buildTarget" -ForegroundColor DarkGray
    $buildOutput = & dotnet build $buildTarget 2>&1 | ForEach-Object { $_.ToString() }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "BUILD FAILED!" -ForegroundColor Red
        $buildOutput | Select-Object -Last 15 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        return $false
    }
    Write-Host "Build OK." -ForegroundColor Green
    return $true
}

# -- Main execution ------------------------------------------------------------

$totalSteps = $AllSteps.Count

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Magenta
Write-Host "  ClaudeCodeOrchestrator - Worker Agent" -ForegroundColor Magenta
Write-Host "  Sequential Step Execution" -ForegroundColor Magenta
Write-Host "======================================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "Plan:   $PlanPath" -ForegroundColor DarkGray
Write-Host "$totalSteps steps | Starting at step $Step | Budget: `$$MaxBudget/step" -ForegroundColor White
if ($DryRun) { Write-Host "[DRY RUN MODE]" -ForegroundColor Yellow }
Write-Host ""

Set-Location $ProjectRoot

for ($i = ($Step - 1); $i -lt $totalSteps; $i++) {
    $current = $AllSteps[$i]
    $stepNum = $i + 1

    Write-StepHeader -StepNum $stepNum -Total $totalSteps -Title $current.title

    # Build prompt with context from previous steps
    $contextSection = Build-ContextSection -CurrentStep $stepNum
    $taskPrompt = if ($contextSection) {
        "${contextSection}TASK:`n$($current.prompt)"
    } else {
        "TASK:`n$($current.prompt)"
    }

    $result = Invoke-Claude -Prompt $taskPrompt -StepName "step${stepNum}_$($current.name)"

    # Store result for context sharing
    $StepResults[$stepNum] = @{
        Name   = $current.name
        Title  = $current.title
        Result = $result.Output
    }

    if (-not $result.Success -and -not $DryRun) {
        Write-Host ""
        Write-Host "Step $stepNum failed. Aborting." -ForegroundColor Red
        Write-Host "To resume: .\claude-worker-agent.ps1 -Step $stepNum" -ForegroundColor Yellow
        exit 1
    }

    # Build check after each step (except DryRun)
    if (-not $DryRun) {
        if (-not (Confirm-BuildSuccess)) {
            Write-Host ""
            Write-Host "Build failed after step $stepNum. Attempting auto-fix..." -ForegroundColor Yellow

            $fixResult = Invoke-Claude -Prompt "The build failed. Run 'dotnet build', read the errors, and fix all compile errors. Commit the fix." -StepName "step${stepNum}_fix"

            if (-not $fixResult.Success -or -not (Confirm-BuildSuccess)) {
                Write-Host "Auto-fix failed. Aborting." -ForegroundColor Red
                Write-Host "To resume: .\claude-worker-agent.ps1 -Step $stepNum" -ForegroundColor Yellow
                exit 1
            }
        }
    }

    Write-Host "Step $stepNum/$totalSteps completed." -ForegroundColor Green
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "  All $totalSteps steps completed!" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host ""
