"""NIP-66 SSL metadata container with test capabilities."""

from __future__ import annotations

import asyncio
import hashlib
import socket
import ssl
from typing import Any, Self

from core.logger import Logger
from models.nips.base import DEFAULT_TIMEOUT, BaseMetadata
from models.relay import NetworkType, Relay

from .data import Nip66SslData
from .logs import Nip66SslLogs


logger = Logger("models.nip66")


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

                if cert:
                    # Subject Common Name
                    subject = cert.get("subject", ())
                    for rdn in subject:
                        for attr, value in rdn:  # type: ignore[misc]
                            if attr == "commonName":
                                result["ssl_subject_cn"] = value
                                break

                    # Issuer organization and CN
                    issuer = cert.get("issuer", ())
                    for rdn in issuer:
                        for attr, value in rdn:  # type: ignore[misc]
                            if attr == "organizationName":
                                result["ssl_issuer"] = value
                            elif attr == "commonName":
                                result["ssl_issuer_cn"] = value

                    # Validity dates
                    not_after = cert.get("notAfter")
                    if not_after and isinstance(not_after, str):
                        result["ssl_expires"] = ssl.cert_time_to_seconds(not_after)

                    not_before = cert.get("notBefore")
                    if not_before and isinstance(not_before, str):
                        result["ssl_not_before"] = ssl.cert_time_to_seconds(not_before)

                    # Subject Alternative Names
                    san_list: list[str] = []
                    for san_type, san_value in cert.get("subjectAltName", ()):  # type: ignore[misc]
                        if san_type == "DNS" and isinstance(san_value, str):
                            san_list.append(san_value)
                    if san_list:
                        result["ssl_san"] = san_list

                    # Serial number
                    serial = cert.get("serialNumber")
                    if serial:
                        result["ssl_serial"] = serial

                    # Version
                    version = cert.get("version")
                    if version is not None:
                        result["ssl_version"] = version

                # SHA-256 fingerprint from binary cert
                if cert_binary:
                    fingerprint = hashlib.sha256(cert_binary).hexdigest().upper()
                    formatted = ":".join(
                        fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)
                    )
                    result["ssl_fingerprint"] = f"SHA256:{formatted}"

                # TLS protocol and cipher
                protocol = ssock.version()
                if protocol:
                    result["ssl_protocol"] = protocol

                cipher_info = ssock.cipher()
                if cipher_info:
                    result["ssl_cipher"] = cipher_info[0]
                    result["ssl_cipher_bits"] = cipher_info[2]
        except ssl.SSLError as e:
            logger.debug("ssl_cert_extraction_failed", error=str(e))
        except Exception as e:
            logger.debug("ssl_cert_extraction_error", error=str(e))

        # Validate certificate separately
        result["ssl_valid"] = False
        try:
            verify_context = ssl.create_default_context()
            with (
                socket.create_connection((host, port), timeout=timeout) as sock2,
                verify_context.wrap_socket(sock2, server_hostname=host),
            ):
                result["ssl_valid"] = True
        except ssl.SSLError:
            pass
        except Exception as e:
            logger.debug("ssl_validation_error", error=str(e))

        return result

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
