param(
    [Parameter(Mandatory = $true)][string]$PortName,
    [Parameter(Mandatory = $true)][int]$BaudRate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$port = $null

try {
    $port = [System.IO.Ports.SerialPort]::new(
        $PortName,
        $BaudRate,
        [System.IO.Ports.Parity]::None,
        8,
        [System.IO.Ports.StopBits]::One
    )
    $port.DtrEnable = $false
    $port.RtsEnable = $false
    $port.NewLine = "`n"
    $port.WriteTimeout = 500
    $port.ReadTimeout = 500
    $port.Open()

    Start-Sleep -Milliseconds 1500
    [Console]::Out.WriteLine("READY")
    [Console]::Out.Flush()

    while ($true) {
        $line = [Console]::In.ReadLine()
        if ($null -eq $line) { break }
        if ($line -eq "__EXIT__") { break }
        if ([string]::IsNullOrWhiteSpace($line)) { continue }

        $port.WriteLine($line)
        $port.BaseStream.Flush()
        [Console]::Out.WriteLine("OK")
        [Console]::Out.Flush()
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    [Console]::Error.Flush()
    exit 1
}
finally {
    if ($null -ne $port) {
        try {
            if ($port.IsOpen) {
                $port.Close()
            }
        }
        catch {
        }

        $port.Dispose()
    }
}
