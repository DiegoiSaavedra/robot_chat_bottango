function Read-HttpRequest {
}
function Read-HttpRequest {
    param([Parameter(Mandatory = $true)][System.Net.Sockets.TcpClient]$Client)

    $stream = $Client.GetStream()
}
function Read-HttpRequest {
    param([Parameter(Mandatory = $true)][System.Net.Sockets.TcpClient]$Client)

    $stream = $Client.GetStream()
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::ASCII, $false, 1024, $true)
}
function Read-HttpRequest {
    $rawPath = '/test?a=1'
    $path = $rawPath.Split('?')[0]
}
function Read-HttpRequest {
    return @{
        Method = 'GET'
    }
}
function Read-HttpRequest {
    $line = 'a:b'
    $separatorIndex = $line.IndexOf(':')
}
