@echo off
chcp 65001 >nul
REM ============================================================
REM  缠论K线分析工具 - Windows 启动脚本 (Web 入口)
REM  用法: start_web.bat [端口]  例如: start_web.bat 8502
REM  默认端口 8501，与 docker-compose.yml 保持一致
REM
REM  行为：
REM   1. 优先使用项目自带 venv；若不存在则自动创建并安装依赖；
REM   2. 环境重装/迁移后旧 venv 失效（关联 Python 被卸载）时，
REM      自动删除并用系统 Python 重建；
REM   3. 启动前自动补齐 requirements.txt 中缺失的包；
REM   4. 任何致命错误/警告信息会停留 5 秒后再关闭窗口。
REM ============================================================

SETLOCAL ENABLEDELAYEDEXPANSION

SET "PORT=8501"
IF NOT "%~1"=="" SET "PORT=%~1"

SET "ROOT=%~dp0"
SET "ENV_FILE=%ROOT%.env"
SET "VENV_DIR=%ROOT%venv"
SET "PYTHON_EXE="
SET "PIP_EXE="

REM ---- 选定 Python 解释器（venv 优先，否则系统 python）----
IF EXIST "%VENV_DIR%\Scripts\python.exe" (
    REM 环境重装/迁移后，旧 venv 可能仍指向已被卸载/移动的 Python，先做健康检查
    "%VENV_DIR%\Scripts\python.exe" -c "import sys" >nul 2>&1
    IF "!ERRORLEVEL!"=="0" (
        SET "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
        SET "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"
        goto :HAVE_PY
    )
    echo [警告] 检测到 venv 已失效（其关联的 Python 已被卸载或移动），正在删除并重建虚拟环境 ...
    RMDIR /S /Q "%VENV_DIR%"
)

REM venv 缺失或失效 -> 尝试用系统 python 创建
REM 依次尝试：本机已知安装路径 -> PATH 中的 python -> py -3 启动器（每步都做可用性校验）
SET "PY_KNOWN=D:\DevEnv\Python\Python312\python.exe"
SET "SYS_PY="
IF EXIST "%PY_KNOWN%" (
    "%PY_KNOWN%" --version >nul 2>&1
    IF "!ERRORLEVEL!"=="0" SET "SYS_PY=%PY_KNOWN%"
)
IF "!SYS_PY!"=="" (
    python --version >nul 2>&1
    IF "!ERRORLEVEL!"=="0" SET "SYS_PY=python"
)
IF "!SYS_PY!"=="" (
    py -3 --version >nul 2>&1
    IF "!ERRORLEVEL!"=="0" SET "SYS_PY=py -3"
)

IF NOT "!SYS_PY!"=="" (
    echo [信息] 未检测到可用虚拟环境，正在基于 !SYS_PY! 创建 venv（首次需联网安装依赖，请耐心等待）...
    !SYS_PY! -m venv "%VENV_DIR%"
    IF NOT EXIST "%VENV_DIR%\Scripts\python.exe" (
        echo [致命错误] 创建虚拟环境失败，请确认系统已安装 Python 3 且 python / py 命令可用。
        echo.
        echo 窗口将在 5 秒后关闭 ...
        timeout /t 5 >nul
        EXIT /B 1
    )
    SET "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
    SET "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"
    goto :HAVE_PY
)

echo [致命错误] 未检测到可用的 Python：系统 PATH 中无 python / py，且项目 venv 缺失或失效。
echo 请先安装 Python 3.10+（https://www.python.org/downloads/），安装时勾选 Add python.exe to PATH。
echo.
echo 窗口将在 5 秒后关闭 ...
timeout /t 5 >nul
EXIT /B 1

:HAVE_PY
echo [信息] 使用 Python 解释器: %PYTHON_EXE%

REM ---- 自动安装依赖（仅补装缺失包，不重复安装已存在的）----
echo [信息] 正在检查并补齐依赖（如需联网下载，请耐心等待）...
"%PIP_EXE%" install --disable-pip-version-check -r "%ROOT%requirements.txt"
IF NOT "%ERRORLEVEL%"=="0" (
    call :FATAL "依赖安装失败，请检查网络或 requirements.txt 内容。"
)

REM ---- 从 .env 读取 APP_PASSWORD ----
SET "APP_PASSWORD="
IF EXIST "%ENV_FILE%" (
    FOR /F "usebackq tokens=1,* delims==" %%A IN ("%ENV_FILE%") DO (
        SET "LINE=%%A"
        REM 跳过注释行
        IF NOT "%%A"=="" (
            SET "FIRST=%%A"
            IF NOT "!FIRST:~0,1!"=="#" (
                IF /I "%%A"=="APP_PASSWORD" SET "APP_PASSWORD=%%B"
            )
        )
    )
)

IF "%APP_PASSWORD%"=="" (
    call :WARN " .env 中未找到 APP_PASSWORD，Web 将以无口令模式启动（WEB 入口会拒绝启动）。请在 .env 中设置 APP_PASSWORD 后重试。"
    timeout /t 5 >nul
    EXIT /B 1
)

REM ---- 检查端口占用（仅判定 LISTENING 状态，排除 TIME_WAIT/SYN_SENT 等瞬时连接）----
SET "PORT_USED=0"
FOR /F "tokens=1,2,3,4,5" %%A IN ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') DO (
    SET "PORT_USED=1"
)
IF "%PORT_USED%"=="1" (
    call :FATAL "端口 %PORT% 已被占用（LISTENING），请先释放该端口或换用其他端口。例如: start_web.bat 8502"
)

echo ============================================================
echo   缠论K线分析工具 Web 启动中...
echo   地址: http://localhost:%PORT%
echo   数据源: 默认 StockDB（本地服务，免 token）
echo ============================================================
echo.

SET "APP_PASSWORD=%APP_PASSWORD%"
CD /D "%ROOT%"

REM ---- 后台拉起 Streamlit（不阻塞 bat，便于随后弹窗提示）----
REM   --browser.gatherUsageStats=false：避免首次启动弹出 Streamlit 邮箱注册提示
REM   --server.headless=true：不自动打开浏览器（脚本/远程场景下避免弹出）
START "" /B "%PYTHON_EXE%" -m streamlit run web/app.py --server.address=0.0.0.0 --server.port=%PORT% --server.headless=true --browser.gatherUsageStats=false

REM ---- 等待端口就绪后弹出"已启动"信息框（开机自启可见）----
SET "READY=0"
FOR /L %%I IN (1,1,30) DO (
    FOR /F "tokens=1,2,3,4,5" %%A IN ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') DO (
        SET "READY=1"
    )
    IF "!READY!"=="1" GOTO :LAUNCHED
    timeout /t 1 >nul
)
:LAUNCHED

REM ---- 内联 VBScript 弹窗：提示已启动 + 访问地址 ----
SET "VBS=%TEMP%\chanlun_launched.vbs"
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Popup "✅ 缠论K线分析工具已启动" ^& vbCrLf ^& vbCrLf ^& "浏览器访问：http://localhost:%PORT%" ^& vbCrLf ^& "数据源：默认 StockDB（本地服务，免 token）", 0, "缠论分析工具", 64
) > "%VBS%"
cscript //nologo "%VBS%"
DEL /F /Q "%VBS%" >nul 2>&1

ENDLOCAL
EXIT /B 0

REM ============================================================
REM  子程序：致命错误 -> 红字提示并停留 5 秒后退出
REM ============================================================
:FATAL
echo.
echo [致命错误] %~1
echo.
echo 窗口将在 5 秒后关闭 ...
timeout /t 5 >nul
goto :TERMINATE

REM ============================================================
REM  子程序：警告 -> 黄字提示（调用方决定是否随后退出）
REM ============================================================
:WARN
echo.
echo [警告] %~1
echo.
goto :EOF

REM ---- 统一终止入口：真正结束本脚本（FATAL 通过 goto 跳出 call 上下文到达此处）----
:TERMINATE
ENDLOCAL
EXIT /B 1
