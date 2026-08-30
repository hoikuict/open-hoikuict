from __future__ import annotations

import argparse
import base64
import ipaddress
import os
import secrets
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _private_bytes(key) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _write_new(path: Path, content: bytes | str, *, private: bool = False) -> None:
    if path.exists():
        raise FileExistsError(f"既存ファイルを上書きしません: {path}")
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    if private:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _powershell_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def create_development_files(output_dir: Path, host: str, port: int, repo: Path) -> None:
    host_ip = ipaddress.ip_address(host)
    output_dir.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "open-hoikuict development CA")]
    )
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, f"open-hoikuict development {host}")]
    )
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(host_ip), x509.DNSName("localhost")]
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    vapid_key = ec.generate_private_key(ec.SECP256R1())
    vapid_public_bytes = vapid_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    vapid_application_server_key = base64.urlsafe_b64encode(vapid_public_bytes).rstrip(b"=").decode("ascii")

    ca_key_path = output_dir / "development-ca-key.pem"
    ca_pem_path = output_dir / "install-on-phone-development-ca.crt"
    ca_der_path = output_dir / "install-on-phone-development-ca.cer"
    server_key_path = output_dir / "server-key.pem"
    server_cert_path = output_dir / "server-certificate.pem"
    vapid_key_path = output_dir / "vapid-private-key.pem"
    vapid_public_path = output_dir / "vapid-public-key.pem"
    launcher_path = output_dir / "start-parent-push-test.ps1"

    _write_new(ca_key_path, _private_bytes(ca_key), private=True)
    _write_new(ca_pem_path, ca_certificate.public_bytes(serialization.Encoding.PEM))
    _write_new(ca_der_path, ca_certificate.public_bytes(serialization.Encoding.DER))
    _write_new(server_key_path, _private_bytes(server_key), private=True)
    _write_new(server_cert_path, server_certificate.public_bytes(serialization.Encoding.PEM))
    _write_new(vapid_key_path, _private_bytes(vapid_key), private=True)
    _write_new(
        vapid_public_path,
        vapid_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )

    origin = f"https://{host}:{port}"
    launcher = f"""$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath {_powershell_literal(repo)}

$env:HOIKUICT_ENV = 'development'
$env:HOIKUICT_DATABASE_URL = 'sqlite:///./hoikuict-parent-auth-check.db'
$env:HOIKUICT_ENABLE_MOCK_AUTH = '1'
$env:HOIKUICT_STAFF_AUTH_MODE = 'mock'
$env:HOIKUICT_PARENT_AUTH_MODE = 'local_password'
$env:HOIKUICT_LOGIN_THROTTLE_HMAC_KEY = {_powershell_literal(secrets.token_urlsafe(40))}
$env:HOIKUICT_SECRET_KEY = {_powershell_literal(secrets.token_urlsafe(40))}
$env:HOIKUICT_CSRF_ENFORCE = '0'
$env:HOIKUICT_COOKIE_SECURE = '1'
$env:HOIKUICT_KIOSK_ACCESS_MODE = 'disabled'
$env:HOIKUICT_PARENT_MAIL_TRANSPORT = 'disabled'

$env:HOIKUICT_PUSH_TRANSPORT = 'webpush'
$env:HOIKUICT_PUSH_VAPID_PUBLIC_KEY = {_powershell_literal(vapid_application_server_key)}
$env:HOIKUICT_PUSH_VAPID_PRIVATE_KEY = {_powershell_literal(vapid_key_path)}
$env:HOIKUICT_PUSH_VAPID_SUBJECT = 'mailto:developer@example.com'
$env:HOIKUICT_PUBLIC_ORIGIN = {_powershell_literal(origin)}

& .\\venv\\Scripts\\python.exe -m uvicorn main:app --host 0.0.0.0 --port {port} --ssl-keyfile {_powershell_literal(server_key_path)} --ssl-certfile {_powershell_literal(server_cert_path)}
"""
    _write_new(launcher_path, launcher)

    print(f"公開URL: {origin}")
    print(f"スマホへインストールするCA証明書: {ca_der_path}")
    print(f"起動スクリプト: {launcher_path}")
    print("秘密鍵の内容は表示していません。このディレクトリを共有しないでください。")


def repair_server_certificate(output_dir: Path, host: str) -> None:
    host_ip = ipaddress.ip_address(host)
    now = datetime.now(timezone.utc)
    ca_key = serialization.load_pem_private_key(
        (output_dir / "development-ca-key.pem").read_bytes(), password=None
    )
    existing_ca_certificate = x509.load_pem_x509_certificate(
        (output_dir / "install-on-phone-development-ca.crt").read_bytes()
    )
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(existing_ca_certificate.subject)
        .issuer_name(existing_ca_certificate.subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    (output_dir / "install-on-phone-development-ca.crt").write_bytes(
        ca_certificate.public_bytes(serialization.Encoding.PEM)
    )
    (output_dir / "install-on-phone-development-ca.cer").write_bytes(
        ca_certificate.public_bytes(serialization.Encoding.DER)
    )
    server_key = serialization.load_pem_private_key(
        (output_dir / "server-key.pem").read_bytes(), password=None
    )
    server_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, f"open-hoikuict development {host}")]
    )
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(host_ip), x509.DNSName("localhost")]
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    certificate_path = output_dir / "server-certificate.pem"
    certificate_path.write_bytes(server_certificate.public_bytes(serialization.Encoding.PEM))
    print(f"サーバー証明書を再発行しました: {certificate_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="保護者Web Push実機確認用の開発証明書とVAPID鍵を生成します。"
    )
    parser.add_argument("--host", required=True, help="スマホから接続するPCのIPv4アドレス")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--repair-existing",
        action="store_true",
        help="既存CAと秘密鍵を維持したままサーバー証明書だけ再発行します",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir.resolve()
    if args.repair_existing:
        repair_server_certificate(output_dir, args.host)
    else:
        create_development_files(output_dir, args.host, args.port, repo)


if __name__ == "__main__":
    main()
