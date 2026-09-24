# 只读诊断: 随时可跑, 不改任何东西。用于确认 WSL Docker 到 Windows 的映射链路状态。
$ErrorActionPreference = 'SilentlyContinue'
$port = 2375

Write-Host "=== 1. WSL 侧状态 ===" -ForegroundColor Cyan
wsl -d Ubuntu -- bash -lc "printf 'dockerd: '; systemctl is-active docker; printf 'TCP 监听: '; (ss -ltnp 2>/dev/null | grep -q ':$port') && echo '有 :$port' || echo '无 :$port (未跑 install.sh)'; printf 'drop-in: '; ls /etc/systemd/system/docker.service.d/ 2>/dev/null | tr '\n' ' '; echo"

Write-Host "`n=== 2. Windows -> daemon 连通性 ===" -ForegroundColor Cyan
$tcp = New-Object System.Net.Sockets.TcpClient
$reachable = $false
try {
    if ($tcp.ConnectAsync('127.0.0.1', $port).Wait(3000) -and $tcp.Connected) { $reachable = $true }
} catch { } finally { $tcp.Close() }
if ($reachable) {
    Write-Host "TCP 127.0.0.1:$port 连通" -ForegroundColor Green
    try {
        $v = Invoke-RestMethod "http://localhost:$port/version" -TimeoutSec 8
        $i = Invoke-RestMethod "http://localhost:$port/info"     -TimeoutSec 8
        Write-Host ("引擎 {0} / API {1} / {2}/{3} / 容器 {4} 运行中, 镜像 {5} 个, RootDir {6}" -f `
            $v.Version, $v.APIVersion, $v.Os, $v.Arch, $i.Containers, $i.Images, $i.DockerRootDir) -ForegroundColor Green
    } catch {
        Write-Host "!! 端口通但 HTTP API 无响应: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "!! 127.0.0.1:$port 不通 —— 映射尚未生效" -ForegroundColor Red
    Write-Host "   在 WSL 内执行: cd /mnt/c/Users/houyunlong/Desktop/campusProject && sudo bash scripts/wsl-docker-tcp/install.sh"
}

Write-Host "`n=== 3. Windows 侧 CLI / context ===" -ForegroundColor Cyan
$d = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($d) {
    Write-Host "docker.exe: $($d.Source)"
    Write-Host "版本: $(& docker version --format '{{.Client.Version}}' 2>$null) (client)"
    & docker context ls | Format-Table -AutoSize | Out-String -Width 120 | Write-Host
    $dh = $env:DOCKER_HOST
    if ($dh) { Write-Host "!! 进程级 DOCKER_HOST=$dh 会覆盖 context" -ForegroundColor Yellow }
} else {
    Write-Host "未安装 docker.exe —— 跑 setup-windows.ps1 装 CLI" -ForegroundColor Yellow
}

Write-Host "`n=== 4. 容器端口从 Windows 可达性(抽样) ===" -ForegroundColor Cyan
if ($reachable) {
    try {
        $cs = Invoke-RestMethod "http://localhost:$port/containers/json" -TimeoutSec 8
        if (-not $cs -or $cs.Count -eq 0) { Write-Host "无运行中容器, 跳过" }
        foreach ($c in $cs) {
            $names = ($c.Names -join ',')
            foreach ($p in ($c.Ports | Where-Object { $_.PublicPort })) {
                $c2 = New-Object System.Net.Sockets.TcpClient
                $st = try { if ($c2.ConnectAsync('127.0.0.1', $p.PublicPort).Wait(2000) -and $c2.Connected) { '连通' } else { '不通' } } catch { '不通' } finally { $c2.Close() }
                Write-Host ("  {0}  宿主:{1} -> 容器:{2}  {3}" -f $names, $p.PublicPort, $p.PrivatePort, $st)
            }
        }
    } catch { Write-Host "查询失败: $($_.Exception.Message)" -ForegroundColor Red }
}
