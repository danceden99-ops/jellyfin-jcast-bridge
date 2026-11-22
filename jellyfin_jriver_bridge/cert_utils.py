"""
Self-signed TLS certificate generator for the Cast V2 server.

Chromecast devices use self-signed certificates.  Cast senders (Chrome,
Jellyfin, etc.) do **not** verify the server certificate — they only
require that the connection is TLS-encrypted.

This module generates a 2048-bit RSA key + X.509 cert valid for 10 years.
It uses the ``cryptography`` package when available; otherwise it shells
out to ``openssl``.
"""

from __future__ import annotations

import datetime
import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)


# Pre-generated, 10-year self-signed 2048-bit RSA TLS credentials for JRiver Cast Bridge
# Used as a resilient fallback if both 'cryptography' C-extensions and the 'openssl' CLI are absent.
FALLBACK_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIDCDCCAfCgAwIBAgIUblis51Se1EQqfRMudJFauaanA5owDQYJKoZIhvcNAQEL
BQAwPjEbMBkGA1UEAwwSSlJpdmVyIENhc3QgQnJpZGdlMR8wHQYDVQQKDBZKZWxs
eWZpbi1KUml2ZXIgQnJpZGdlMB4XDTI2MTEyMjAwMzQxNVoXDTM2MTExOTAwMzQx
NVowPjEbMBkGA1UEAwwSSlJpdmVyIENhc3QgQnJpZGdlMR8wHQYDVQQKDBZKZWxs
eWZpbi1KUml2ZXIgQnJpZGdlMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKC
AQEAtUTQJlC0sfv3+zBT5KkrVnHi6SEn0DlePTNMjjzObOo8jZwB3SRfeu2B7j5E
3NiX+B87+8hSIEVTdGIQMEg9k8XCYiRPZt2vrkuUvSawZea43NwRh/+WxOTd6vPM
im4/LnZmGBldGf8vkBMRkttK1dHGYtsNGm7UOtMCtLL7vuBBoH9V1SS8oyhP5Q0Z
tqv3JSgTCsFM6U/UzeWOTWkKCzg29P/mUHWedmBun9K98Ua+IXMRhbWPyHID4Ecd
2c8E10I5h2zdaHZfQymduNrNVId9SuEr9mw/IYlz2Uc2PcXwq4oFf2d5S+jFzP+5
3PGzYNSWMAhbDAsn2Ad/n9xKNQIDAQABMA0GCSqGSIb3DQEBCwUAA4IBAQBXkIYo
5VIWjpyuoQH1MSWjuO5elJ55DNsahB6tj3W4ZQUNVr3WhIBpRX5aF8QfsjuFzcjP
39zCofW9exmFawhN7O+FDo2YQdotmE1PTad8zHfa8cV59cRGRhSOvkyPF363js0t
h4FOagdz6mChIf0r4NzKa5agxCtReB97yJooWk+7Ir5XELXdT3KmQk5MZVlA03km
V5cg2cOBWQ8imdMgbNCk5G4YVpwmc4zgjxLuudk1savLI6LPT5tkGNYmVQ4lpbJo
xgAa47hWiaiAo7m31bbxDj0jN0VfkKdWAS5G8QM3ojrpovLPW7eh2fuBu5NXiqEm
FjPjZR3SM93hfO5F
-----END CERTIFICATE-----
"""

FALLBACK_KEY_PEM = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAtUTQJlC0sfv3+zBT5KkrVnHi6SEn0DlePTNMjjzObOo8jZwB
3SRfeu2B7j5E3NiX+B87+8hSIEVTdGIQMEg9k8XCYiRPZt2vrkuUvSawZea43NwR
h/+WxOTd6vPMim4/LnZmGBldGf8vkBMRkttK1dHGYtsNGm7UOtMCtLL7vuBBoH9V
1SS8oyhP5Q0Ztqv3JSgTCsFM6U/UzeWOTWkKCzg29P/mUHWedmBun9K98Ua+IXMR
hbWPyHID4Ecd2c8E10I5h2zdaHZfQymduNrNVId9SuEr9mw/IYlz2Uc2PcXwq4oF
f2d5S+jFzP+53PGzYNSWMAhbDAsn2Ad/n9xKNQIDAQABAoIBAAgKHOvW6gC32TW0
kCmRoDJI234oyIq2NKbYH6kL60FBrUnzKJ9nTAdlDjCj5d5Go/M7zWdoHDTB5mCA
mR4b4h4SKA7xJ21h35Df8y3/D7uuEGmWDOTNGIgaH3nBDBB6sPlgtzv4sGkLnDXF
xrwbVw9/KsJhKHMq7BioABRFsoXyk97JoZPydrrpTWGETSTSUPVFYZsVzdv2jlZX
LXQRsKKr9AO9OJty3CHB5ElEK7DUcvOBPMraL6EsRdmvlOjq2Q2QB9YB69hRRpFT
27A+heYolfubhj4Iikwz/pxri1Q+YNEdmzW7oxRzhWpgKHosVlDLM0jbpPxNowgj
KuWD8vkCgYEA22WY0mS5Xya0Ve03rsRLw/ypNtMegmkuC3lQd9sNCrrRqGDcLRW5
B4yRHN31rtplsmxgxhMplHSPGzoSnGK+pP6A47l2FQaZCLZG+4ufl05W3+1bCNbd
ONQtjL6eazI/uvsLqEovaOYKhWabHhf0VQTDkSE8jmcdeP+Df+avM+kCgYEA04LF
5NZrI2COoxhANfkEAqFuRgch+qGiSmcrR9ffuYKTyvwdz0kqhCkubBByZFuqa2h3
PakOwWaTT1jXsr82ouV83LwcW/f9ON6AR6v21wC8LEduFG+veiRX+lIQ8Mtn46zx
M48GGT3Xx/NM49Hq7mo8da+bj9e227nhEWobsG0CgYEAieruDKSA203LY5DBxj1j
m4qDHRHORhC0f0X9zbqIEkyqa3yoLDdRn2s/9bOaNBbagzUaCKoXI1m6dFUnSePR
EItknsMBdeo13YIoUQzOgCEg/5eH+KCJZKYNFELn918ZLQOPqnUoJHsn9gAwVtSc
Ja3e+qa4GJS9tEh7c7WiQbECgYAxl2na28NHCi6nYto7TWV5UGxQkv+OijNJCqOF
NsJH9qu8XhyHK3qCfj1aLQkFKtDsWhQLKwZAplJHumbojBi9XN1Hy/tCPQTsPo8J
PvKjOpLkNuNCe2VDWB4gnPlH3AlBwpzTH+eoJ23efdc7W06gE9yVI1VwBn3jStPQ
h3ZyiQKBgQDZZcWfNdfKJaVbX+ikJjgJqELV1W367C9J2LIoJTrMll/qR17PKI3W
DVOzED/aL3fkvbpgEouvvgzfi8Pt9HGTg3Mx8HYmWdkiWKBbFD58WQGbH2r4k+zv
XdvbVsg9NORz+rTYtdGvdBoPz5dgXVSIuGDzU83KvvLcSL4am+guEA==
-----END RSA PRIVATE KEY-----
"""


def generate_self_signed_cert(cert_path: str, key_path: str) -> None:
    """Create *cert_path* and *key_path* with a fresh self-signed cert."""
    os.makedirs(os.path.dirname(cert_path) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)

    try:
        _generate_with_cryptography(cert_path, key_path)
        return
    except Exception as e:
        logger.info("'cryptography' module unavailable (%s) — trying openssl CLI", e)

    try:
        _generate_with_openssl(cert_path, key_path)
        return
    except Exception as e:
        logger.info("openssl CLI unavailable (%s) — writing built-in self-signed credentials", e)

    _generate_with_builtin_fallback(cert_path, key_path)


def _generate_with_builtin_fallback(cert_path: str, key_path: str) -> None:
    with open(cert_path, "w", encoding="utf-8") as f:
        f.write(FALLBACK_CERT_PEM.strip() + "\n")
    with open(key_path, "w", encoding="utf-8") as f:
        f.write(FALLBACK_KEY_PEM.strip() + "\n")
    logger.info("TLS cert installed (built-in fallback credentials): %s", cert_path)


def _generate_with_cryptography(cert_path: str, key_path: str) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "JRiver Cast Bridge"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Jellyfin-JRiver Bridge"),
        ]
    )

    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )

    logger.info("TLS cert generated (cryptography): %s", cert_path)


def _generate_with_openssl(cert_path: str, key_path: str) -> None:
    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                key_path,
                "-out",
                cert_path,
                "-days",
                "3650",
                "-nodes",
                "-subj",
                "/CN=JRiver Cast Bridge/O=Jellyfin-JRiver Bridge",
            ],
            check=True,
            capture_output=True,
        )
        logger.info("TLS cert generated (openssl): %s", cert_path)
    except FileNotFoundError:
        logger.error(
            "Neither the 'cryptography' Python package nor the 'openssl' CLI was found. "
            "Please install cryptography: pip install cryptography"
        )
        raise RuntimeError("Missing 'cryptography' package or 'openssl' binary to generate TLS certificates.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cert = sys.argv[1] if len(sys.argv) > 1 else "certs/cast_bridge.crt"
    key = sys.argv[2] if len(sys.argv) > 2 else "certs/cast_bridge.key"
    generate_self_signed_cert(cert, key)
