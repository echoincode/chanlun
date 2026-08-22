@echo off
chcp 65001 >nul
REM ============================================================
REM  缠论K线分析工具 - Windows 启动脚本 (Web 入口)
REM  用法: start_web.bat [端口]  例如: start_web.bat 8502
REM  默认端口 8501，与 docker-compose.yml 保持一致
REM ============================================================

SETLOCAL ENABLEDELAYEDEXPANSION

SET "PORT=8501"
IF NOT "%~1"=="" SET "PORT=%~1"

SET "ROOT=%~dp0"
SET "ENV_FILE=%ROOT%.env"

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
    echo [警告] .env 中未找到 APP_PASSWORD，Web 将以无口令模式启动（WEB 入口会拒绝启动）。
    echo          请在 .env 中设置 APP_PASSWORD 后重试。
    pause
    EXIT /B 1
)

REM ---- 检查端口占用（仅判定 LISTENING 状态，排除 TIME_WAIT/SYN_SENT 等瞬时连接）----
SET "PORT_USED=0"
FOR /F "tokens=1,2,3,4,5" %%A IN ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') DO (
    SET "PORT_USED=1"
)
IF "%PORT_USED%"=="1" (
    echo [错误] 端口 %PORT% 已被占用（LISTENING），请先释放该端口或换用其他端口。
    echo        例如: start_web.bat 8502
    pause
    EXIT /B 1
)

REM ---- 检查依赖 ----
python -c "import streamlit" 2>nul || (
    echo [错误] 未安装 streamlit，请先执行: pip install -r requirements.txt
    pause
    EXIT /B 1
)

echo ============================================================
echo   缠论K线分析工具 Web 启动中...
echo   地址: http://localhost:%PORT%
echo   数据源: 默认 Baostock（前端可切换 Tushare）
echo ============================================================
echo.

SET "APP_PASSWORD=%APP_PASSWORD%"
CD /D "%ROOT%"
streamlit run web/app.py --server.address=0.0.0.0 --server.port=%PORT%

ENDLOCAL
