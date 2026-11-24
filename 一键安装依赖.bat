@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo ============================================================
echo   QuantumChem AI v0.1.0 - 一键安装与环境初始化向导
echo   作者：钱昌天（首都师范大学物理系，北京 100048）
echo ============================================================
echo.

set "UV_CMD="
where uv >nul 2>nul
if %errorlevel%==0 set "UV_CMD=uv"
if not defined UV_CMD if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"

if not defined UV_CMD (
    echo [错误] 未检测到 uv 包管理器。
    echo.
    echo 请先打开 PowerShell 并运行以下命令安装 uv，然后重新双击本脚本：
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo.
    pause
    exit /b 1
)

echo [1/3] 正在同步 Python 3.12 虚拟环境与全部依赖（uv sync）...
"%UV_CMD%" sync
if errorlevel 1 (
    echo.
    echo [错误] 依赖同步失败，请检查网络连接或 Python 环境后重试。
    pause
    exit /b 1
)

echo.
echo [2/3] 正在检查 Playwright Chromium（用于 A4 PDF 报告编译）...
"%UV_CMD%" run playwright install chromium
if errorlevel 1 (
    echo [警告] Playwright Chromium 安装未完成（若当前离线可暂忽略，Web 工作台与核心功能仍可正常使用）。
)

echo.
echo [3/3] 正在检查本地配置文件...
if not exist "config\settings.toml" (
    if exist "config\settings.example.toml" (
        copy /Y "config\settings.example.toml" "config\settings.toml" >nul
        echo 已从模板生成 config\settings.toml，请按需在 Web「6. 设置」或配置文件中填写服务信息。
    )
) else (
    echo 已保留现有 config\settings.toml。
)

echo.
echo ============================================================
echo   安装与初始化完成！接下来您可以：
echo   1. 双击「启动量子化学助手.bat」启动桌面科研工作台；
echo   2. 双击「启动量子化学助手(模拟演示).bat」无需服务器立即演示；
echo   3. 双击「生成桌面快捷方式.bat」在桌面创建带图标快捷方式；
echo   4. 查看「使用说明.md」或「使用说明.pdf」了解详细操作指南。
echo ============================================================
echo.
pause
