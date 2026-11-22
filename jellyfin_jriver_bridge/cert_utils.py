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


def generate_self_signed_cert(cert_path: str, key_path: str) -> None:
    """Create *cert_path* and *key_path* with a fresh self-signed cert."""
    os.makedirs(os.path.dirname(cert_path) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)

    try:
        _generate_with_cryptography(cert_path, key_path)
    except ImportError:
        logger.info("'cryptography' not installed — falling back to openssl CLI")
        _generate_with_openssl(cert_path, key_path)


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
