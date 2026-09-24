# Windows 侧: 安装 Docker CLI(仅 CLI, 不是 Docker Desktop), 并把默认 context 指向 WSL 内的引擎。
# 前提: 已在 WSL 内执行过 install.sh。
# 可重复执行(幂等)。
$ErrorActionPreference = 'Stop'

$CtxName  = 'wsl'
$TcpHost  = if ($env:DOCKER_TCP_ENDPOINT) { $env:DOCKER_TCP_ENDPOINT } else { 'tcp://127.0.0.1:2375' }
$TcpPort  = 2375

Write-Host "=== 0. 确认 WSL 侧端口就绪 ===" -ForegroundColor Cyan
$tcp = New-Object System.Net.Sockets.TcpClient
try {
    if (-not ($tcp.ConnectAsync('127.0.0.1', $TcpPort).Wait(3000) -and $tcp.Connected)) { throw }
    Write-Host "127.0.0.1:$TcpPort 可连通" -ForegroundColor Green
} catch {
    Write-Host "!! 连不上 127.0.0.1:$TcpPort。请先在 WSL 内执行:" -ForegroundColor Red
    Write-Host "     cd /mnt/c/Users/houyunlong/Desktop/campusProject && sudo bash scripts/wsl-docker-tcp/install.sh"
    exit 1
} finally { $tcp.Close() }

Write-Host "`n=== 1. 安装 Docker CLI ===" -ForegroundColor Cyan
$docker = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($docker) {
    Write-Host "已存在: $($docker.Source)"
} else {
    winget install --id Docker.DockerCLI --exact --accept-package-agreements --accept-source-agreements
    # portable 包装完, 当前会话 PATH 还没有新目录, 手动刷新一次
    $env:Path = "{0};{1}" -f [Environment]::GetEnvironmentVariable('Path', 'Machine'),
                              [Environment]::GetEnvironmentVariable('Path', 'User')
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Host "!! 安装完成但仍找不到 docker.exe, 请重开一个 PowerShell 窗口再跑本脚本" -ForegroundColor Red
        exit 1
    }
    Write-Host "已安装: $($docker.Source)" -ForegroundColor Green
}

Write-Host "`n=== 2. 检查会覆盖 context 的 DOCKER_HOST ===" -ForegroundColor Cyan
foreach ($scope in 'Process', 'User', 'Machine') {
    $v = if ($scope -eq 'Process') { $env:DOCKER_HOST } else { [Environment]::GetEnvironmentVariable('DOCKER_HOST', $scope) }
    if ($v) { Write-Host ("!! {0,-8} DOCKER_HOST={1}  (它会压过 context, 需确认是不是你想要的)" -f $scope, $v) -ForegroundColor Yellow }
    else     { Write-Host ("{0,-8} 未设置" -f $scope) }
}

Write-Host "`n=== 3. 建立并启用 context ===" -ForegroundColor Cyan
if (((docker context ls --format '{{.Name}}')) -contains $CtxName) {
    docker context update $CtxName --docker "host=$TcpHost" | Out-Null
    Write-Host "context '$CtxName' 已存在, 重新指向 $TcpHost"
} else {
    docker context create $CtxName --docker "host=$TcpHost" | Out-Null
    Write-Host "已创建 context '$CtxName' -> $TcpHost"
}
docker context use $CtxName

Write-Host "`n=== 4. 验证 ===" -ForegroundColor Cyan
docker version --format 'Client={{.Client.Version}}  Engine={{.Server.Version}}  ServerOS={{.Server.Os}}/{{.Server.Arch}}'
Write-Host "`n当前容器:"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

Write-Host "`n注意: portable 包不含 compose 插件, Windows 侧没有 'docker compose' 子命令;" -ForegroundColor Yellow
Write-Host "      compose 仍走 WSL:  wsl -d Ubuntu docker compose ..." -ForegroundColor Yellow
