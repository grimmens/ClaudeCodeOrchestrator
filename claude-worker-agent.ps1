#Requires -Version 7.0
<#
.SYNOPSIS
    SpeiseDirekt Claude Worker Agent - Orchestriert Claude Code fuer phasenweise Entwicklung.

.DESCRIPTION
    Fuehrt die Roadmap-Phasen aus .claude/plans/wild-greeting-boot.md Schritt fuer Schritt aus.
    Jeder Schritt wird von einer eigenen Claude-Session abgearbeitet und committet.

.PARAMETER PlanFile
    Pfad zur JSON-Datei mit den Instruktionen/Todos. Default: todos.json

.PARAMETER Phase
    Welche Phase ausgefuehrt werden soll (1, 2, 3, ...). Default: 1

.PARAMETER Step
    Ab welchem Schritt innerhalb der Phase gestartet wird (1, 2, 3, ...). Default: 1

.PARAMETER DryRun
    Zeigt die Prompts an ohne sie auszufuehren.

.PARAMETER MaxBudget
    Max USD Budget pro Schritt. Default: 5.00

.EXAMPLE
    .\claude-worker-agent.ps1 -Phase 1
    .\claude-worker-agent.ps1 -PlanFile .\other-plan.json -Phase 2
    .\claude-worker-agent.ps1 -Phase 1 -Step 2
    .\claude-worker-agent.ps1 -Phase 1 -DryRun
#>

param(
    [string]$PlanFile = "todos.json",
    [int]$Phase = 1,
    [int]$Step = 1,
    [switch]$DryRun,
    [double]$MaxBudget = 5.00
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$RoadmapFile = ".claude/plans/wild-greeting-boot.md"
$LogDir = Join-Path $ProjectRoot ".claude/logs"

# ── Plan aus JSON laden ─────────────────────────────────────────────────────
$PlanPath = if ([System.IO.Path]::IsPathRooted($PlanFile)) { $PlanFile } else { Join-Path $ProjectRoot $PlanFile }
if (-not (Test-Path $PlanPath)) {
    Write-Host "Plan-Datei nicht gefunden: $PlanPath" -ForegroundColor Red
    exit 1
}
$AllTodos = Get-Content $PlanPath -Raw | ConvertFrom-Json

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

function Write-StepHeader {
    param([string]$PhaseNum, [string]$StepNum, [string]$Title)
    $separator = "=" * 70
    Write-Host ""
    Write-Host $separator -ForegroundColor Cyan
    Write-Host "  Phase $PhaseNum | Schritt $StepNum | $Title" -ForegroundColor Cyan
    Write-Host $separator -ForegroundColor Cyan
    Write-Host ""
}

function Invoke-Claude {
    param(
        [string]$Prompt,
        [string]$StepName
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
    $logFile = Join-Path $LogDir "${timestamp}_${StepName}.log"

    if ($DryRun) {
        Write-Host "[DRY RUN] Wuerde ausfuehren:" -ForegroundColor Yellow
        Write-Host $Prompt -ForegroundColor Gray
        Write-Host ""
        return $true
    }

    Write-Host "Starte Claude-Session..." -ForegroundColor Green
    Write-Host "Log: $logFile" -ForegroundColor DarkGray

    $fullPrompt = @"
KONTEXT: Du arbeitest am SpeiseDirekt3-Projekt. Die Roadmap liegt in $RoadmapFile.
Die shared Class Library 'SpeiseDirekt.Model' existiert bereits mit Models, DbContext, Services.
Das Blazor-Web-Projekt ist 'SpeiseDirekt3'. Branch: feature/extract-class-library.

WICHTIG:
- Lies zuerst den Plan in $RoadmapFile um den Gesamtkontext zu verstehen.
- Arbeite NUR den unten beschriebenen Schritt ab, nicht mehr.
- Stelle sicher dass 'dotnet build' am Ende ohne Fehler durchlaeuft.
- Committe deine Aenderungen mit einer aussagekraeftigen Commit-Message.
- Wenn du auf Probleme stoesst, behebe sie selbststaendig.

AUFGABE:
$Prompt
"@

    try {
        $output = claude -p $fullPrompt --allowedTools "Read" "Write" "Edit" "Bash" "Glob" "Grep" --max-turns 50 --max-budget-usd $MaxBudget 2>&1
        $output | Out-File -FilePath $logFile -Encoding utf8
        $exitCode = $LASTEXITCODE

        if ($exitCode -ne 0) {
            Write-Host "WARNUNG: Claude beendet mit Exit-Code $exitCode" -ForegroundColor Red
            Write-Host "Details im Log: $logFile" -ForegroundColor Red
            return $false
        }

        # Letzte 5 Zeilen als Zusammenfassung anzeigen
        $lastLines = ($output | Select-Object -Last 5) -join "`n"
        Write-Host "Ergebnis:" -ForegroundColor Green
        Write-Host $lastLines -ForegroundColor Gray
        Write-Host ""
        return $true
    }
    catch {
        Write-Host "FEHLER: $_" -ForegroundColor Red
        return $false
    }
}

function Confirm-BuildSuccess {
    Write-Host "Pruefe Build..." -ForegroundColor Yellow
    $buildOutput = dotnet build 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "BUILD FEHLGESCHLAGEN!" -ForegroundColor Red
        $buildOutput | Select-Object -Last 10 | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        return $false
    }
    Write-Host "Build erfolgreich." -ForegroundColor Green
    return $true
}

# ── Todos nach Phase gruppieren ──────────────────────────────────────────────

$Phases = @{}
foreach ($todo in $AllTodos) {
    $p = [int]$todo.phase
    if (-not $Phases.ContainsKey($p)) { $Phases[$p] = @() }
    $Phases[$p] += @{
        Name   = $todo.name
        Title  = $todo.title
        Prompt = $todo.prompt
    }
}

# ── Hauptlogik ────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║         SpeiseDirekt - Claude Worker Agent                  ║" -ForegroundColor Magenta
Write-Host "║         Autonome Phasen-Orchestrierung                     ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""

if (-not $Phases.ContainsKey($Phase)) {
    Write-Host "Phase $Phase nicht definiert. Verfuegbare Phasen: $($Phases.Keys -join ', ')" -ForegroundColor Red
    exit 1
}

$steps = $Phases[$Phase]
$totalSteps = $steps.Count

Write-Host "Plan: $PlanPath" -ForegroundColor DarkGray
Write-Host "Phase $Phase | $totalSteps Schritte | Start bei Schritt $Step | Budget: `$$MaxBudget/Schritt" -ForegroundColor White
if ($DryRun) { Write-Host "[DRY RUN MODUS]" -ForegroundColor Yellow }
Write-Host ""

Set-Location $ProjectRoot

for ($i = ($Step - 1); $i -lt $totalSteps; $i++) {
    $currentStep = $steps[$i]
    $stepNum = $i + 1

    Write-StepHeader -PhaseNum $Phase -StepNum "$stepNum/$totalSteps" -Title $currentStep.Title

    $success = Invoke-Claude -Prompt $currentStep.Prompt -StepName "phase${Phase}_${stepNum}_$($currentStep.Name)"

    if (-not $success -and -not $DryRun) {
        Write-Host ""
        Write-Host "Schritt $stepNum fehlgeschlagen. Abbruch." -ForegroundColor Red
        Write-Host "Zum Fortsetzen: .\claude-worker-agent.ps1 -Phase $Phase -Step $stepNum" -ForegroundColor Yellow
        exit 1
    }

    # Build-Check nach jedem Schritt (ausser DryRun)
    if (-not $DryRun) {
        if (-not (Confirm-BuildSuccess)) {
            Write-Host ""
            Write-Host "Build fehlgeschlagen nach Schritt $stepNum. Versuche automatische Reparatur..." -ForegroundColor Yellow

            $fixSuccess = Invoke-Claude -Prompt "Der Build ist fehlgeschlagen. Lies die Build-Fehler mit 'dotnet build' und behebe alle Compile-Errors. Committe den Fix." -StepName "phase${Phase}_${stepNum}_fix"

            if (-not $fixSuccess -or -not (Confirm-BuildSuccess)) {
                Write-Host "Automatische Reparatur fehlgeschlagen. Abbruch." -ForegroundColor Red
                Write-Host "Zum Fortsetzen: .\claude-worker-agent.ps1 -Phase $Phase -Step $stepNum" -ForegroundColor Yellow
                exit 1
            }
        }
    }

    Write-Host "Schritt $stepNum/$totalSteps abgeschlossen." -ForegroundColor Green
}

Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Phase $Phase vollstaendig abgeschlossen!" -ForegroundColor Green
Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""

if ($Phase -lt ($Phases.Keys | Measure-Object -Maximum).Maximum) {
    $nextPhase = $Phase + 1
    Write-Host "Naechste Phase: .\claude-worker-agent.ps1 -Phase $nextPhase" -ForegroundColor Cyan
}
