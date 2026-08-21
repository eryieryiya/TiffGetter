<#
.SYNOPSIS
    将 TiffGetter 打包为独立 exe（PyInstaller onefile，GUI + CLI 统一入口）。

.DESCRIPTION
    - 自动选择构建环境：显式参数 > TIFFGETTER_BUILD_PYTHON > 当前 python（有 PyInstaller 时）
      > Anaconda base（上次成功构建的环境）
    - 自动补齐缺失依赖：pyinstaller、tkcalendar（可用 -NoInstallDeps 禁止自动安装）
    - 打包产物：dist/TiffGetter.exe
    - 打包后自动验证：CLI --help、GUI 启动冒烟测试、归档内容检查

.EXAMPLE
    .\build_exe.ps1                              # 自动探测环境并打包
    .\build_exe.ps1 -Python C:\Python312\python.exe   # 指定解释器
    .\build_exe.ps1 -NoInstallDeps               # 不自动安装依赖，缺依赖即报错
    .\build_exe.ps1 -SkipVerify                  # 跳过打包后验证
#>
param(
    [string]$Python = '',
    [switch]$NoInstallDeps,
    [switch]$SkipVerify
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$CondaBase = 'D:\ProgramData\anaconda3\python.exe'

function Find-BuildPython {
    if ($Python) { return (Resolve-Path $Python).Path }
    if ($env:TIFFGETTER_BUILD_PYTHON) { return $env:TIFFGETTER_BUILD_PYTHON }

    # 优先当前激活的 python（若带 PyInstaller）
    $cur = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($cur) {
        & $cur -m PyInstaller --version *>$null
        if ($LASTEXITCODE -eq 0) { return $cur }
    }
    # 其次 conda base（本机验证可用的构建环境）
    if (Test-Path $CondaBase) { return $CondaBase }
    if ($cur) { return $cur }
    throw '未找到可用的 Python 解释器；可用 -Python 显式指定'
}

function Test-Module([string]$py, [string]$module) {
    & $py -c "import $module" 2>$null
    return $LASTEXITCODE -eq 0
}

function Install-IfMissing([string]$py, [string]$module) {
    if (Test-Module $py $module) { return }
    if ($NoInstallDeps) {
        throw "缺少依赖: $module（已指定 -NoInstallDeps，跳过安装）"
    }
    Write-Host "[*] 安装缺失依赖: $module ..." -ForegroundColor Cyan
    & $py -m pip install $module
    if ($LASTEXITCODE -ne 0) { throw "安装 $module 失败" }
}

Write-Host '=' * 62 -ForegroundColor DarkCyan
Write-Host ' TiffGetter 打包脚本 (PyInstaller onefile)' -ForegroundColor DarkCyan
Write-Host '=' * 62 -ForegroundColor DarkCyan

# ---- 1. 环境探测 ----
$py = Find-BuildPython
Write-Host "[*] 构建 Python: $py"
& $py --version
if ($LASTEXITCODE -ne 0) { throw 'Python 解释器不可用' }

# ---- 2. 依赖检查 ----
Install-IfMissing $py 'PyInstaller'
Install-IfMissing $py 'tkcalendar'   # ui_main.py 顶层导入（日期选择器）

# rasterio 必须可导入（环境损坏时提前报错，给出指引）
if (-not (Test-Module $py 'rasterio')) {
    throw "当前环境 rasterio 不可用（可能缺 expat/GDAL DLL）。`n" +
          "建议改用已验证的 conda base: -Python $CondaBase"
}

$pyVer = & $py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$riVer = & $py -c "import rasterio; print(rasterio.__version__)"
Write-Host "[*] Python $pyVer + rasterio $riVer + PyInstaller $(& $py -m PyInstaller --version)"

# ---- 3. 打包 ----
Write-Host ''
Write-Host '[*] 开始打包（onefile，约需 2-5 分钟）...' -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean --log-level WARN TiffGetter.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 打包失败' }

$exe = Join-Path $Root 'dist\TiffGetter.exe'
if (-not (Test-Path $exe)) { throw "打包完成但未找到产物: $exe" }
$sizeMb = '{0:N1}' -f ((Get-Item $exe).Length / 1MB)
Write-Host "[*] 产物: $exe ($sizeMb MB)" -ForegroundColor Green

# ---- 4. 验证 ----
if ($SkipVerify) {
    Write-Host '[!] 已跳过验证（-SkipVerify）'
    exit 0
}

Write-Host ''
Write-Host '[*] 验证 1/3: CLI 模式（--help）...' -ForegroundColor Cyan
& $exe --help *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'CLI 验证失败：exe --help 非零退出（运行时依赖缺失？）'
}
Write-Host '     PASS: CLI --help 正常' -ForegroundColor Green

Write-Host '[*] 验证 2/3: GUI 启动冒烟测试（15 秒存活 + 无 traceback）...' -ForegroundColor Cyan
$stderrFile = Join-Path $env:TEMP "tiffgetter_gui_smoke_$PID.err.log"
$p = Start-Process -FilePath $exe -PassThru -RedirectStandardError $stderrFile
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    if ($p.HasExited) { break }
}
if ($p.HasExited) {
    $err = ''
    if (Test-Path $stderrFile) { $err = Get-Content $stderrFile -Raw }
    Remove-Item $stderrFile -ErrorAction SilentlyContinue
    throw "GUI 验证失败：进程提前退出（退出码 $($p.ExitCode)）`n$err"
}
$errText = ''
if (Test-Path $stderrFile) { $errText = Get-Content $stderrFile -Raw }
if ($errText -match 'Traceback|TclError') {
    taskkill /PID $p.Id /T /F *> $null   # 杀整棵进程树（onefile 父+子）
    Remove-Item $stderrFile -ErrorAction SilentlyContinue
    throw "GUI 验证失败：进程虽存活但输出含异常：`n$errText"
}
taskkill /PID $p.Id /T /F *> $null       # 杀整棵进程树，避免子进程残留占用控制台
Remove-Item $stderrFile -ErrorAction SilentlyContinue
Write-Host '     PASS: GUI 窗口正常启动（15s 内无异常退出，已自动关闭）' -ForegroundColor Green

Write-Host '[*] 验证 3/3: 归档关键数据检查...' -ForegroundColor Cyan
$listing = & $py -m PyInstaller.utils.cliutils.archive_viewer -l $exe 2>$null
foreach ($needle in @('config.yaml', 'gdalvrt.xsd', 'proj.db')) {
    $found = $listing -match [regex]::Escape($needle)
    if ($found) {
        Write-Host "     PASS: 包含 $needle" -ForegroundColor Green
    } else {
        Write-Host "     WARN: 归档中未找到 $needle"
    }
}

Write-Host ''
Write-Host '=' * 62 -ForegroundColor DarkCyan
Write-Host " 打包完成: $exe ($sizeMb MB)" -ForegroundColor Green
Write-Host ' 使用: 双击运行 GUI；命令行模式见 --help' -ForegroundColor DarkCyan
Write-Host '=' * 62 -ForegroundColor DarkCyan