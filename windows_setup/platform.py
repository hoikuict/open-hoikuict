"""Windows operations with fixed commands and validated, non-executable inputs."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import ipaddress
import os
from pathlib import Path
import subprocess
import uuid

from beta_setup.core import SetupError, clean_environment, reject_links
from windows_setup.configuration import service_name


def is_admin() -> bool:
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def run(arguments: list[str], *, timeout: int = 60, environment: dict | None = None) -> str:
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=timeout, env=environment or clean_environment(),
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise SetupError("Windowsの設定操作を完了できませんでした。権限とサービスの状態を確認してください。", "windows_operation_failed")
    return result.stdout.decode("utf-8-sig", errors="replace").strip()


def powershell(script: str, values: dict | None = None, *, timeout: int = 60):
    if os.name != "nt":
        raise SetupError("Windows 11で実行してください。", "windows_required")
    system = Path(os.environ["SystemRoot"]) / "System32"
    executable = system / "WindowsPowerShell/v1.0/powershell.exe"
    environment = clean_environment()
    environment["PSModulePath"] = str(system / "WindowsPowerShell/v1.0/Modules")
    environment["HOIKUICT_SETUP_INPUT"] = json.dumps(values or {}, ensure_ascii=True)
    prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $v=ConvertFrom-Json $env:HOIKUICT_SETUP_INPUT; "
    encoded = base64.b64encode((prefix + script).encode("utf-16-le")).decode("ascii")
    raw = run([str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
              environment=environment, timeout=timeout)
    return json.loads(raw) if raw else None


def network_adapters() -> list[dict]:
    result = powershell("""
    $items=@(Get-NetIPConfiguration | ForEach-Object {
      $n=$_; $p=Get-NetConnectionProfile -InterfaceIndex $n.InterfaceIndex -ErrorAction SilentlyContinue
      foreach($a in $n.IPv4Address) {
        if($a.IPAddress -notlike '169.254.*' -and $a.IPAddress -ne '127.0.0.1') {
          [pscustomobject]@{id=[string]$n.InterfaceIndex; name=$n.InterfaceAlias;
            ip=$a.IPAddress; prefix=$a.PrefixLength; private=($p.NetworkCategory -eq 'Private');
            pcName=$env:COMPUTERNAME; mac=$n.NetAdapter.MacAddress;
            gateway=(@($n.IPv4DefaultGateway.NextHop) -join ', ')}
        }
      }
    }); ConvertTo-Json -InputObject $items -Compress
    """)
    items = result or []
    for item in items:
        item['subnet'] = str(ipaddress.IPv4Network(f"{item['ip']}/{item['prefix']}", strict=False))
    return items


def current_sid() -> str:
    return powershell("[Security.Principal.WindowsIdentity]::GetCurrent().User.Value | ConvertTo-Json -Compress")


def known_folder(kind: str) -> Path:
    ids = {"data": "62ab5d82-fdc1-4dc3-a9dd-070d1d495d97",
           "program": "905e63b6-c1bf-494e-b29c-65b732d3d21a"}
    raw = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(ids[kind]).bytes_le)
    output = ctypes.c_wchar_p()
    shell = ctypes.WinDLL("shell32")
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    if shell.SHGetKnownFolderPath(raw, 0, None, ctypes.byref(output)) != 0:
        raise SetupError("Windowsの保存先を確認できませんでした。", "windows_path_failed")
    try:
        return Path(output.value)
    finally:
        ole = ctypes.WinDLL("ole32")
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole.CoTaskMemFree(ctypes.cast(output, ctypes.c_void_p))


def instance_paths(instance: str) -> tuple[Path, Path]:
    service_name(instance)
    return (known_folder("program") / "OpenHoikuICT" / instance,
            known_folder("data") / "OpenHoikuICT" / instance)


def restrict_directory(path: Path, *, service: str | None = None, writable: bool = False,
                       owner_sid: str | None = None) -> None:
    reject_links(path)
    if not path.is_dir():
        raise SetupError("保護するフォルダーを確認できません。", "path_invalid")
    entries = [{"identity": "S-1-5-18", "rights": "FullControl", "sid": True},
               {"identity": "S-1-5-32-544", "rights": "FullControl", "sid": True}]
    if service:
        entries.append({"identity": "NT SERVICE\\" + service,
                        "rights": "Modify" if writable else "ReadAndExecute", "sid": False})
    if owner_sid:
        import re
        if not re.fullmatch(r"S-1-[0-9-]+", owner_sid):
            raise SetupError("導入者の識別情報を確認できません。", "owner_invalid")
        entries.append({"identity": owner_sid, "rights": "FullControl", "sid": True})
    # Change only the DACL, including explicit grants from a previous attempt.
    # Set-Acl may also try to persist audit information and request
    # SeSecurityPrivilege, which the unelevated coordinator must not need.
    powershell("""
      $directory=[IO.DirectoryInfo]::new($v.path)
      $acl=$directory.GetAccessControl([Security.AccessControl.AccessControlSections]::Access)
      $acl.SetAccessRuleProtection($true,$false)
      foreach($rule in @($acl.Access)){ [void]$acl.RemoveAccessRuleSpecific($rule) }
      foreach($entry in $v.entries){
        $identity=if($entry.sid){[Security.Principal.SecurityIdentifier]::new($entry.identity)}
                  else{[Security.Principal.NTAccount]::new($entry.identity)}
        $rule=[Security.AccessControl.FileSystemAccessRule]::new(
          $identity,$entry.rights,'ContainerInherit,ObjectInherit','None','Allow')
        $acl.AddAccessRule($rule)
      }
      $directory.SetAccessControl($acl)
    """, {"path": str(path), "entries": entries})


def service_state(instance: str) -> dict:
    name = service_name(instance)
    result = powershell("""
    $s=Get-CimInstance Win32_Service -Filter ("Name='" + $v.name + "'")
    if($null -eq $s){ @{exists=$false} | ConvertTo-Json -Compress }
    else { @{exists=$true; state=$s.State; path=$s.PathName; account=$s.StartName} | ConvertTo-Json -Compress }
    """, {"name": name})
    return result


def install_service(code: Path, root: Path, instance: str) -> None:
    name = service_name(instance)
    if service_state(instance)["exists"]:
        raise SetupError("同名のWindowsサービスが存在します。上書きせず停止しました。", "service_exists")
    wrapper = code / "service.exe"
    run([str(wrapper), "install"])
    sc = str(Path(os.environ["SystemRoot"]) / "System32/sc.exe")
    # A virtual account has no password and no administrator membership.
    # Virtual accounts require a NULL password in ChangeServiceConfig, not an
    # empty password string. Omitting password= makes sc.exe pass NULL.
    run([sc, "config", name, "obj=", "NT SERVICE\\" + name])
    run([sc, "sidtype", name, "unrestricted"])
    restrict_directory(code, service=name)
    restrict_directory(root, service=name, writable=True)
    # Immutable secret/config directory may only be read by the service.
    restrict_directory(root / "config", service=name)


def change_service(code: Path, instance: str, operation: str) -> None:
    if operation not in {"start", "stop", "uninstall"}:
        raise ValueError("invalid service operation")
    state = service_state(instance)
    expected = str(code / "service.exe").casefold()
    if not state["exists"]:
        if operation in {"stop", "uninstall"}:
            return
        raise SetupError("Windowsサービスが見つかりません。", "service_missing")
    if state["path"].strip('"').casefold() != expected:
        raise SetupError("サービスの実行元が異なります。操作を中止しました。", "service_mismatch")
    if operation == "stop" and state["state"] == "Stopped":
        return
    def wait_for(status):
        powershell("""
          $service=Get-Service -Name $v.name -ErrorAction Stop
          try { $service.WaitForStatus([ServiceProcess.ServiceControllerStatus]$v.status,[TimeSpan]::FromSeconds(60)) }
          finally { $service.Dispose() }
        """, {"name": service_name(instance), "status": status}, timeout=75)
    if operation == "start" and state["state"] == "Stop Pending":
        wait_for("Stopped")
    pending = {"start": "Start Pending", "stop": "Stop Pending"}
    if state["state"] != pending.get(operation):
        run([str(code / "service.exe"), operation], timeout=90)
    # WinSW can return while SCM is still starting/stopping the service.
    # Do not restart, migrate data, or delete files until SCM confirms it.
    if operation in pending:
        wait_for("Running" if operation == "start" else "Stopped")


def firewall(lan: dict, instance: str, *, remove: bool = False) -> None:
    name = service_name(instance) + "-LAN"
    if remove:
        powershell("Get-NetFirewallRule -Name $v.name -ErrorAction SilentlyContinue | Remove-NetFirewallRule", {"name": name})
        return
    powershell("""
    if(Get-NetFirewallRule -Name $v.name -ErrorAction SilentlyContinue){throw 'rule exists'}
    $a=Get-NetAdapter -InterfaceIndex ([int]$v.adapter)
    New-NetFirewallRule -Name $v.name -DisplayName $v.name -Direction Inbound -Action Allow
      -Protocol TCP -LocalPort 443 -LocalAddress $v.ip -RemoteAddress $v.subnet
      -Profile Private -InterfaceAlias $a.Name | Out-Null
    """.replace("\n      ", " "), {"name": name, **{key: lan[key] for key in ("adapter", "ip", "subnet")}})


def power_settings(*, prevent_sleep: bool | None = None) -> dict:
    # Read/modify the active scheme's AC sleep timeout, not unrelated settings.
    return powershell("""
    $scheme=(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power\\User\\PowerSchemes').ActivePowerScheme
    $path='HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power\\User\\PowerSchemes\\'+$scheme+'\\238c9fa8-0aad-41ed-83f4-97be242c8f20\\29f6c1db-86da-48c5-9fdb-f2b67b1f44da'
    $old=(Get-ItemProperty $path).ACSettingIndex
    if($null -ne $v.seconds){ & "$env:SystemRoot\\System32\\powercfg.exe" /setacvalueindex $scheme SUB_SLEEP STANDBYIDLE $v.seconds | Out-Null
      if($LASTEXITCODE -ne 0){throw 'power setting failed'}
      & "$env:SystemRoot\\System32\\powercfg.exe" /setactive $scheme | Out-Null
      if($LASTEXITCODE -ne 0){throw 'power activation failed'} }
    @{scheme=$scheme; seconds=$old} | ConvertTo-Json -Compress
    """, {"seconds": 0 if prevent_sleep else None})


def restore_power(value: dict) -> None:
    powershell("""
    $active=(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power\\User\\PowerSchemes').ActivePowerScheme
    if($active -ne $v.scheme){throw 'active scheme changed'}
    & "$env:SystemRoot\\System32\\powercfg.exe" /setacvalueindex $v.scheme SUB_SLEEP STANDBYIDLE ([int]$v.seconds) | Out-Null
    if($LASTEXITCODE -ne 0){throw 'power restore failed'}
    & "$env:SystemRoot\\System32\\powercfg.exe" /setactive $v.scheme | Out-Null
    """, value)


class ElevatedProcess:
    def __init__(self, handle):
        self.handle = handle

    def poll(self):
        if not self.handle:
            return 0
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            return None
        return None if code.value == 259 else code.value

    def close(self):
        if self.handle:
            kernel = ctypes.WinDLL("kernel32")
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(self.handle)
            self.handle = None


def elevate(executable: Path, arguments: list[str]) -> ElevatedProcess:
    class ExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]
    info = ExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x400  # retain process handle; no asynchronous shell call
    info.lpVerb = "runas"
    info.lpFile = str(executable)
    info.lpParameters = subprocess.list2cmdline(arguments)
    info.nShow = 0
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise SetupError("Windowsの管理者許可が得られませんでした。設定は変更していません。", "admin_declined")
    return ElevatedProcess(info.hProcess)
