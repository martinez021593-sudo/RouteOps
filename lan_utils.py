import base64
import ipaddress
import socket
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import qrcode
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


def get_lan_ip():
    candidates = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.connect(("10.255.255.255", 1))
        candidates.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            candidates.append(info[4][0])
    except Exception:
        pass
    for ip in candidates:
        try:
            addr = ipaddress.ip_address(ip)
            if addr.version == 4 and not addr.is_loopback and not addr.is_link_local:
                return ip
        except Exception:
            pass
    return "127.0.0.1"


def _write_key(path, key):
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))


def _load_key(path):
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _write_cert(path, cert):
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def ensure_lan_certificates(base_dir, lan_ip):
    base_dir = Path(base_dir)
    cert_dir = base_dir / "certs"
    cert_dir.mkdir(exist_ok=True)
    ca_key_path = cert_dir / "routeops-lan-ca.key"
    ca_cert_path = cert_dir / "routeops-lan-ca.crt"
    server_key_path = cert_dir / "routeops-lan-server.key"
    server_cert_path = cert_dir / "routeops-lan-server.crt"
    ios_profile_path = cert_dir / "routeops-lan-ios.mobileconfig"
    now = datetime.now(timezone.utc)

    if not ca_key_path.exists() or not ca_cert_path.exists():
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RouteOps LAN Pilot"),
            x509.NameAttribute(NameOID.COMMON_NAME, "RouteOps LAN CA"),
        ])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True, key_encipherment=False, content_commitment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False
            ), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        _write_key(ca_key_path, ca_key)
        _write_cert(ca_cert_path, ca_cert)
    else:
        ca_key = _load_key(ca_key_path)
        ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())

    regenerate = True
    if server_cert_path.exists() and server_key_path.exists():
        try:
            cert = x509.load_pem_x509_certificate(server_cert_path.read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            ips = {str(x) for x in san.get_values_for_type(x509.IPAddress)}
            if lan_ip in ips and cert.not_valid_after_utc > now + timedelta(days=30):
                regenerate = False
        except Exception:
            pass

    if regenerate:
        server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RouteOps LAN Pilot"),
            x509.NameAttribute(NameOID.COMMON_NAME, lan_ip),
        ])
        sans = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(lan_ip)))
        except Exception:
            pass
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(ca_cert.subject)
            .public_key(server_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        _write_key(server_key_path, server_key)
        _write_cert(server_cert_path, cert)

    ca_der = x509.load_pem_x509_certificate(ca_cert_path.read_bytes()).public_bytes(serialization.Encoding.DER)
    cert_b64 = base64.b64encode(ca_der).decode("ascii")
    payload_uuid = str(uuid.uuid4()).upper()
    cert_uuid = str(uuid.uuid4()).upper()
    profile = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
<key>PayloadContent</key><array><dict>
<key>PayloadCertificateFileName</key><string>RouteOps LAN CA</string>
<key>PayloadContent</key><data>{cert_b64}</data>
<key>PayloadDescription</key><string>Certificado raíz local para RouteOps LAN Pilot.</string>
<key>PayloadDisplayName</key><string>RouteOps LAN CA</string>
<key>PayloadIdentifier</key><string>com.routeops.lan.ca</string>
<key>PayloadType</key><string>com.apple.security.root</string>
<key>PayloadUUID</key><string>{cert_uuid}</string>
<key>PayloadVersion</key><integer>1</integer>
</dict></array>
<key>PayloadDescription</key><string>Habilita HTTPS local para RouteOps en esta red.</string>
<key>PayloadDisplayName</key><string>RouteOps LAN Pilot</string>
<key>PayloadIdentifier</key><string>com.routeops.lan.profile</string>
<key>PayloadOrganization</key><string>RouteOps</string>
<key>PayloadRemovalDisallowed</key><false/>
<key>PayloadType</key><string>Configuration</string>
<key>PayloadUUID</key><string>{payload_uuid}</string>
<key>PayloadVersion</key><integer>1</integer>
</dict></plist>""".format(cert_b64=cert_b64, cert_uuid=cert_uuid, payload_uuid=payload_uuid)
    ios_profile_path.write_text(profile, encoding="utf-8")

    return {
        "cert_dir": cert_dir,
        "ca_cert": ca_cert_path,
        "ca_key": ca_key_path,
        "server_cert": server_cert_path,
        "server_key": server_key_path,
        "ios_profile": ios_profile_path,
    }


def qr_png_bytes(text):
    qr = qrcode.QRCode(box_size=7, border=3)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
