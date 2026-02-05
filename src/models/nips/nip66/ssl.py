"""NIP-66 SSL metadata container with test capabilities."""

from __future__ import annotations

import asyncio
import hashlib
import socket
import ssl
from typing import Any, Self

from logger import Logger
from models.nips.base import DEFAULT_TIMEOUT, BaseMetadata
from models.relay import Relay
from utils.network import NetworkType

from .data import Nip66SslData
from .logs import Nip66SslLogs


logger = Logger("models.nip66")


# -----------------------------------------------------------------------------
# Certificate Extractor Helper
# -----------------------------------------------------------------------------


class CertificateExtractor:
    """Helper class to extract fields from X509 certificate dict."""

    @staticmethod
    def extract_subject_cn(cert: dict[str, Any]) -> str | None:
        """Extract subject Common Name from certificate."""
        subject = cert.get("subject", ())
        for rdn in subject:
            for attr, value in rdn:
                if attr == "commonName":
                    return str(value)
        return None

    @staticmethod
    def extract_issuer(cert: dict[str, Any]) -> dict[str, str]:
        """Extract issuer organization and CN from certificate."""
        result: dict[str, str] = {}
        issuer = cert.get("issuer", ())
        for rdn in issuer:
            for attr, value in rdn:
                if attr == "organizationName":
                    result["ssl_issuer"] = str(value)
                elif attr == "commonName":
                    result["ssl_issuer_cn"] = str(value)
        return result

    @staticmethod
    def extract_validity(cert: dict[str, Any]) -> dict[str, float]:
        """Extract validity dates (notAfter, notBefore) from certificate."""
        result: dict[str, float] = {}

        not_after = cert.get("notAfter")
        if not_after and isinstance(not_after, str):
            result["ssl_expires"] = ssl.cert_time_to_seconds(not_after)

        not_before = cert.get("notBefore")
        if not_before and isinstance(not_before, str):
            result["ssl_not_before"] = ssl.cert_time_to_seconds(not_before)

        return result

    @staticmethod
    def extract_san(cert: dict[str, Any]) -> list[str] | None:
        """Extract Subject Alternative Names (DNS entries) from certificate."""
        san_list: list[str] = []
        for san_type, san_value in cert.get("subjectAltName", ()):
            if san_type == "DNS" and isinstance(san_value, str):
                san_list.append(san_value)
        return san_list if san_list else None

    @staticmethod
    def extract_serial_and_version(cert: dict[str, Any]) -> dict[str, Any]:
        """Extract serial number and version from certificate."""
        result: dict[str, Any] = {}

        serial = cert.get("serialNumber")
        if serial:
            result["ssl_serial"] = serial

        version = cert.get("version")
        if version is not None:
            result["ssl_version"] = version

        return result

    @staticmethod
    def extract_fingerprint(cert_binary: bytes) -> str:
        """Compute SHA-256 fingerprint from binary certificate."""
        fingerprint = hashlib.sha256(cert_binary).hexdigest().upper()
        formatted = ":".join(fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2))
        return f"SHA256:{formatted}"

    @classmethod
    def extract_all(cls, cert: dict[str, Any]) -> dict[str, Any]:
        """Extract all certificate fields into a single dict."""
        result: dict[str, Any] = {}

        subject_cn = cls.extract_subject_cn(cert)
        if subject_cn:
            result["ssl_subject_cn"] = subject_cn

        result.update(cls.extract_issuer(cert))
        result.update(cls.extract_validity(cert))

        san = cls.extract_san(cert)
        if san:
            result["ssl_san"] = san

        result.update(cls.extract_serial_and_version(cert))

        return result


# -----------------------------------------------------------------------------
# SSL Metadata Class
# -----------------------------------------------------------------------------


class Nip66SslMetadata(BaseMetadata):
    """Container for SSL data and logs with test capabilities."""

    data: Nip66SslData
    logs: Nip66SslLogs

    # -------------------------------------------------------------------------
    # SSL Test
    # -------------------------------------------------------------------------

    @staticmethod
    def _ssl(host: str, port: int, timeout: float) -> dict[str, Any]:
        """Synchronous SSL check with certificate extraction."""
        result: dict[str, Any] = {}

        # Extract certificate data (non-validating context)
        result.update(Nip66SslMetadata._extract_certificate_data(host, port, timeout))

        # Validate certificate separately (validating context)
        result["ssl_valid"] = Nip66SslMetadata._validate_certificate(host, port, timeout)

        return result

    @staticmethod
    def _extract_certificate_data(host: str, port: int, timeout: float) -> dict[str, Any]:
        """Extract certificate data without validation."""
        result: dict[str, Any] = {}
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        try:
            with (
                socket.create_connection((host, port), timeout=timeout) as sock,
                context.wrap_socket(sock, server_hostname=host) as ssock,
            ):
                cert = ssock.getpeercert()
                cert_binary = ssock.getpeercert(binary_form=True)

                # Extract certificate fields
                if cert:
                    result.update(CertificateExtractor.extract_all(cert))

                # Extract fingerprint from binary cert
                if cert_binary:
                    result["ssl_fingerprint"] = CertificateExtractor.extract_fingerprint(
                        cert_binary
                    )

                # Extract TLS connection info
                result.update(Nip66SslMetadata._extract_tls_info(ssock))

        except ssl.SSLError as e:
            logger.debug("ssl_cert_extraction_failed", error=str(e))
        except Exception as e:
            logger.debug("ssl_cert_extraction_error", error=str(e))

        return result

    @staticmethod
    def _extract_tls_info(ssock: ssl.SSLSocket) -> dict[str, Any]:
        """Extract TLS protocol and cipher information."""
        result: dict[str, Any] = {}

        protocol = ssock.version()
        if protocol:
            result["ssl_protocol"] = protocol

        cipher_info = ssock.cipher()
        if cipher_info:
            result["ssl_cipher"] = cipher_info[0]
            result["ssl_cipher_bits"] = cipher_info[2]

        return result

    @staticmethod
    def _validate_certificate(host: str, port: int, timeout: float) -> bool:
        """Validate certificate with full chain verification."""
        try:
            verify_context = ssl.create_default_context()
            with (
                socket.create_connection((host, port), timeout=timeout) as sock,
                verify_context.wrap_socket(sock, server_hostname=host),
            ):
                return True
        except ssl.SSLError:
            return False
        except Exception as e:
            logger.debug("ssl_validation_error", error=str(e))
            return False

    @classmethod
    async def ssl(
        cls,
        relay: Relay,
        timeout: float | None = None,
    ) -> Self:
        """Test SSL certificate for relay.

        Raises:
            ValueError: If non-clearnet relay.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("ssl_testing", relay=relay.url, timeout_s=timeout)

        if relay.network != NetworkType.CLEARNET:
            raise ValueError(f"SSL test requires clearnet, got {relay.network.value}")

        data: dict[str, Any] = {}
        logs: dict[str, Any] = {"success": False, "reason": None}
        port = relay.port or 443

        try:
            logger.debug("ssl_checking", host=relay.host, port=port)
            data = await asyncio.to_thread(cls._ssl, relay.host, port, timeout)
            if data:
                logs["success"] = True
                logger.debug("ssl_checked", relay=relay.url, valid=data.get("ssl_valid"))
            else:
                logs["reason"] = "no certificate data extracted"
                logger.debug("ssl_no_data", relay=relay.url)
        except Exception as e:
            logs["reason"] = str(e)
            logger.debug("ssl_error", relay=relay.url, error=str(e))

        return cls(
            data=Nip66SslData.model_validate(Nip66SslData.parse(data)),
            logs=Nip66SslLogs.model_validate(logs),
        )
