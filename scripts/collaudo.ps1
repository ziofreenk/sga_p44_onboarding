<#
.SYNOPSIS
  Collaudo #8 del POC P44 Automatic onboarding sul PC Windows (Python 3.12, nessun privilegio admin).

.DESCRIPTION
  Esegue in sequenza, dalla radice del repo:
    1. Ambiente  : versione Python (attesa 3.12.x), sqlite, sistema operativo, proxy di sistema
    2. Test      : suite unittest completa (python -m unittest discover -s tests -t . -v)
    3. Demo      : 95 giorni virtuali col mock in-process, confronto con i KPI attesi (seed 44)
    4. Prova CLI : mock su porta reale (default 8044) + 2 cicli orchestratore + report KPI
  Tutto finisce in output\collaudo\<timestamp>\ (log, report, esito.md). Non modifica file del repo.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collaudo.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collaudo.ps1 -Python C:\Tools\python312\python.exe
#>
param(
    [string]$Python = "",          # percorso di python.exe; vuoto = py -3.12, poi python
    [string]$DataRif = "2026-11-12",
    [int]$Porta = 8044,
    [switch]$SaltaTest,            # utile per ripetere solo demo e prova CLI
    [switch]$ConsentiAltraVersione # prosegue anche se Python non è 3.12.x
)

$ErrorActionPreference = "Stop"
$Radice = Split-Path -Parent $PSScriptRoot
Set-Location $Radice
$env:PYTHONUTF8 = "1"              # I/O in UTF-8 anche con output rediretto su file
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1" # niente __pycache__ nel repo durante il collaudo

$Run = Join-Path $Radice ("output\collaudo\" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $Run | Out-Null
$Esiti = New-Object System.Collections.Generic.List[object]

function Scrivi([string]$testo, [string]$colore = "Gray") { Write-Host $testo -ForegroundColor $colore }

function Registra([string]$passo, [bool]$ok, [string]$dettaglio) {
    $Esiti.Add([pscustomobject]@{ Passo = $passo; Esito = $(if ($ok) { "OK" } else { "KO" }); Dettaglio = $dettaglio })
    Scrivi ("  -> {0}: {1}  {2}" -f $passo, $(if ($ok) { "OK" } else { "KO" }), $dettaglio) $(if ($ok) { "Green" } else { "Red" })
}

# Esegue python con argomenti, stdout/stderr su file; restituisce l'exit code
function Quota([string[]]$argomenti) {
    # Start-Process (PS 5.1) unisce gli argomenti con spazi senza virgolette: quotiamo quelli con spazi
    return $argomenti | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
}

function Esegui-Python([string[]]$argomenti, [string]$nomeLog) {
    $out = Join-Path $Run "$nomeLog.log"
    $err = Join-Path $Run "$nomeLog.err.log"
    $p = Start-Process -FilePath $script:PyExe -ArgumentList (Quota $argomenti) -WorkingDirectory $Radice `
        -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -Wait -PassThru
    return $p.ExitCode
}

function Leggi([string]$nomeLog) { return [string](Get-Content -Raw -Encoding UTF8 (Join-Path $Run $nomeLog)) }

# GET/POST verso il mock SENZA proxy di sistema (WebClient con Proxy = $null)
function Chiama-Mock([string]$path, [string]$corpoJson = $null) {
    $wc = New-Object System.Net.WebClient
    $wc.Proxy = $null
    $wc.Encoding = [System.Text.Encoding]::UTF8
    try {
        if ($corpoJson) { $wc.Headers.Add("Content-Type", "application/json"); return $wc.UploadString("http://127.0.0.1:$Porta$path", $corpoJson) }
        return $wc.DownloadString("http://127.0.0.1:$Porta$path")
    } finally { $wc.Dispose() }
}

# ------------------------------------------------------------------ 1. Ambiente
Scrivi "== 1. Ambiente" "Cyan"
if (-not $Python) {
    try { $Python = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null) } catch { $Python = "" }
    if (-not $Python) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source }
    }
}
if (-not $Python -or -not (Test-Path $Python)) {
    Scrivi "Python non trovato. Indicare il percorso con -Python <...\python.exe>" "Red"; exit 1
}
$script:PyExe = $Python
$info = & $PyExe -c "import sys, sqlite3, platform, urllib.request as u; print(platform.python_version()); print(sqlite3.sqlite_version); print(platform.platform()); print(u.getproxies())"
$versione, $sqlite, $so, $proxy = $info
@(
    "Data collaudo : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "Utente / PC   : $env:USERNAME / $env:COMPUTERNAME",
    "Repo          : $Radice",
    "Commit        : $(try { (& git -C $Radice rev-parse --short HEAD 2>$null) } catch { 'n/d' })",
    "Python        : $versione ($PyExe)",
    "SQLite        : $sqlite",
    "Sistema       : $so",
    "PowerShell    : $($PSVersionTable.PSVersion)",
    "Proxy sistema : $proxy"
) | Set-Content -Encoding UTF8 (Join-Path $Run "ambiente.txt")
Get-Content (Join-Path $Run "ambiente.txt") | ForEach-Object { Scrivi "  $_" }
$ok312 = $versione -like "3.12.*"
Registra "Ambiente" $ok312 "Python $versione"
if (-not $ok312 -and -not $ConsentiAltraVersione) { Scrivi "Serve Python 3.12.x (oppure -ConsentiAltraVersione)" "Red"; exit 1 }

# ------------------------------------------------------------------ 2. Test
if (-not $SaltaTest) {
    Scrivi "== 2. Test unittest (circa 1-2 minuti)" "Cyan"
    $t0 = Get-Date
    # unittest scrive il riepilogo su stderr: lo leggiamo da test.err.log
    $rc = Esegui-Python @("-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v") "test"
    $log = Leggi "test.err.log"
    $ran = [regex]::Match($log, "Ran (\d+) tests? in ([\d\.]+)s")
    $fail = [regex]::Match($log, "FAILED \(([^)]*)\)")
    $dett = if ($ran.Success) { "$($ran.Groups[1].Value) test in $([math]::Round([double]$ran.Groups[2].Value, 1)) s" } else { "riepilogo non trovato" }
    if ($fail.Success) { $dett += " - FAILED ($($fail.Groups[1].Value))" }
    Registra "Test unittest" ($rc -eq 0) "$dett (exit $rc, durata $([int]((Get-Date) - $t0).TotalSeconds) s)"
}

# ------------------------------------------------------------------ 3. Demo 95 giorni
Scrivi "== 3. Demo 95 giorni virtuali" "Cyan"
$t0 = Get-Date
$rc = Esegui-Python @("-m", "src.onboarding.demo", "--data-rif", $DataRif, "--cartella", (Join-Path $Run "demo"), "--quiet") "demo"
$out = Leggi "demo.log"
$atteso = "invitati 30, accettati 20 (66,7%), rifiutati 5, tentativi esauriti 5, in corso 0, anomalie 12"
$okDemo = ($rc -eq 0) -and $out.Contains($atteso)
Registra "Demo 95 giorni" $okDemo "exit $rc, durata $([int]((Get-Date) - $t0).TotalSeconds) s, KPI $(if ($out.Contains($atteso)) { 'come attesi' } else { 'DIVERSI dagli attesi' })"

# ------------------------------------------------------------------ 4. Prova CLI su porta reale
Scrivi "== 4. Prova CLI: mock su porta $Porta + 2 cicli orchestratore + report" "Cyan"
$cli = Join-Path $Run "cli"
New-Item -ItemType Directory -Force -Path $cli | Out-Null
$okCli = $false; $dett = ""; $mock = $null
try {
    # porta libera?
    $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Porta)
    try { $l.Start(); $l.Stop() } catch { throw "porta $Porta occupata (usare -Porta)" }

    $rc = Esegui-Python @("-m", "src.onboarding.genera_dati_fittizi", "--data-rif", $DataRif,
        "--csv", "$cli\vettori_fittizi.csv", "--scenari", "$cli\scenari.json") "cli_genera"
    if ($rc -ne 0) { throw "generatore dati: exit $rc" }

    $mock = Start-Process -FilePath $PyExe -WorkingDirectory $Radice -NoNewWindow -PassThru `
        -ArgumentList (Quota @("-m", "src.p44_mock", "--port", "$Porta", "--db", "$cli\p44_mock.db",
                        "--mail-dir", "$cli\mail", "--scenari", "$cli\scenari.json", "--quiet")) `
        -RedirectStandardOutput "$Run\cli_mock.log" -RedirectStandardError "$Run\cli_mock.err.log"
    $pronto = $false
    for ($i = 0; $i -lt 40 -and -not $pronto; $i++) {
        Start-Sleep -Milliseconds 250
        try { Chiama-Mock "/_sim/reset" ('{"now":"' + ([datetime]$DataRif).AddDays(1).ToString("yyyy-MM-dd") + 'T07:00:00Z"}') | Out-Null; $pronto = $true } catch { }
    }
    if (-not $pronto) { throw "il mock non risponde su 127.0.0.1:$Porta (vedi cli_mock.err.log)" }

    $argOrch = @("-m", "src.onboarding.orchestratore", "--csv", "$cli\vettori_fittizi.csv", "--orologio", "mock",
                 "--base-url", "http://127.0.0.1:$Porta", "--db", "$cli\orchestratore.db", "--output", "$cli\output")
    $rc1 = Esegui-Python $argOrch "cli_ciclo1"
    Chiama-Mock "/_sim/clock" '{"advanceDays":3}' | Out-Null       # +3 giorni: scatta il sollecito 1
    $rc2 = Esegui-Python $argOrch "cli_ciclo2"
    $rc3 = Esegui-Python @("-m", "src.onboarding.report_kpi", "--input", "$cli\output") "cli_report"

    $inviti = @(Get-ChildItem "$cli\mail" -Filter *.eml -ErrorAction SilentlyContinue).Count
    $solleciti = @(Get-ChildItem "$cli\output\solleciti" -Filter *.eml -ErrorAction SilentlyContinue).Count
    $report = Test-Path "$cli\output\report\report_kpi.md"
    $dett = "cicli exit $rc1/$rc2, report exit $rc3, mail invito $inviti, solleciti $solleciti"
    $okCli = ($rc1 -eq 0) -and ($rc2 -eq 0) -and ($rc3 -eq 0) -and ($inviti -ge 30) -and ($solleciti -gt 0) -and $report
} catch {
    $dett = "$_"
} finally {
    if ($mock -and -not $mock.HasExited) { Stop-Process -Id $mock.Id -Force }
}
Registra "Prova CLI porta $Porta" $okCli $dett

# ------------------------------------------------------------------ Esito
$tutto = -not ($Esiti | Where-Object { $_.Esito -ne "OK" })
$righe = @("# Esito collaudo #8 - $(Get-Date -Format 'yyyy-MM-dd HH:mm')", "",
           "Esito complessivo: **$(if ($tutto) { 'SUPERATO' } else { 'NON SUPERATO' })**", "",
           "| Passo | Esito | Dettaglio |", "|---|---|---|")
$righe += $Esiti | ForEach-Object { "| $($_.Passo) | $($_.Esito) | $($_.Dettaglio) |" }
$righe += @("", "## File", "- Ambiente: ambiente.txt", "- Log: test.err.log, demo.log, cli_*.log",
            "- Report demo da rivedere: demo\report\report_kpi.md, kpi.csv, anomalie.csv",
            "- Checklist revisione report: docs\collaudo.md")
$righe | Set-Content -Encoding UTF8 (Join-Path $Run "esito.md")
Scrivi ""
Scrivi ("Esito complessivo: " + $(if ($tutto) { "SUPERATO" } else { "NON SUPERATO" })) $(if ($tutto) { "Green" } else { "Red" })
Scrivi "Cartella del collaudo: $Run"
if ($tutto) { exit 0 } else { exit 1 }
