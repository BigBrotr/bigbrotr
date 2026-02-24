"""
NIP-66 SSL metadata container with certificate inspection capabilities.

Connects to a relay's TLS endpoint, extracts certificate details (subject,
issuer, validity, SANs, fingerprint, cipher), and separately validates the
certificate chain as part of
[NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md) monitoring.
Clearnet relays only.

Note:
    The SSL test uses a two-connection methodology:

    1. **Extraction** -- connects with ``CERT_NONE`` to obtain the
       DER-encoded certificate regardless of chain validity, then parses
       it with the ``cryptography`` library.  This allows inspecting
       self-signed or expired certificates.
    2. **Validation** -- connects with the default (validating) SSL context
       to verify the certificate chain against the system trust store.

    Both connections are synchronous socket operations delegated to a thread
    pool via ``asyncio.to_thread`` to avoid blocking the event loop.

See Also:
    [bigbrotr.nips.nip66.data.Nip66SslData][bigbrotr.nips.nip66.data.Nip66SslData]:
        Data model for SSL certificate fields.
    [bigbrotr.nips.nip66.logs.Nip66SslLogs][bigbrotr.nips.nip66.logs.Nip66SslLogs]:
        Log model for SSL inspection results.
    [bigbrotr.utils.transport.InsecureWebSocketTransport][bigbrotr.utils.transport.InsecureWebSocketTransport]:
        Related insecure transport used for WebSocket connections (distinct
        from the raw socket approach used here for certificate extraction).
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import logging
import socket
import ssl
from typing import Any, Self

from cryptography import x509
from cryptography.x509.oid import NameOID

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.nips.base import BaseNipMetadata
from bigbrotr.utils.transport import DEFAULT_TIMEOUT

from .data import Nip66SslData
from .logs import Nip66SslLogs


logger = logging.getLogger("bigbrotr.nips.nip66")


class CertificateExtractor:
    """Extracts structured fields from SSL certificates.

    Supports both the Python ``ssl`` module dict format (from
    ``SSLSocket.getpeercert()``) and ``cryptography`` X.509 objects
    (from DER-encoded certificates).

    See Also:
        [Nip66SslMetadata][bigbrotr.nips.nip66.ssl.Nip66SslMetadata]:
            Container that uses this extractor during certificate inspection.
        [bigbrotr.nips.nip66.data.Nip66SslData][bigbrotr.nips.nip66.data.Nip66SslData]:
            Data model populated by the extracted fields.
    """

    @staticmethod
    def extract_subject_cn(cert: dict[str, Any]) -> str | None:
        """Extract the subject Common Name (CN) from the certificate."""
        subject = cert.get("subject", ())
        for rdn in subject:
            for attr, value in rdn:
                if attr == "commonName":
                    return str(value)
        return None

    @staticmethod
    def extract_issuer(cert: dict[str, Any]) -> dict[str, str]:
        """Extract issuer organization name and CN from the certificate."""
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
        """Extract notAfter and notBefore dates as Unix timestamps."""
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
        """Extract DNS Subject Alternative Names from the certificate."""
        san_list: list[str] = []
        for san_type, san_value in cert.get("subjectAltName", ()):
            if san_type == "DNS" and isinstance(san_value, str):
                san_list.append(san_value)
        return san_list or None

    @staticmethod
    def extract_serial_and_version(cert: dict[str, Any]) -> dict[str, Any]:
        """Extract serial number and X.509 version from the certificate."""
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
        """Compute a SHA-256 fingerprint from the DER-encoded certificate.

        Returns:
            Colon-separated hex string prefixed with ``SHA256:``.
        """
        fingerprint = hashlib.sha256(cert_binary).hexdigest().upper()
        formatted = ":".join(fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2))
        return f"SHA256:{formatted}"

    @classmethod
    def extract_all(cls, cert: dict[str, Any]) -> dict[str, Any]:
        """Extract all available fields from a certificate into a flat dictionary."""
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

    @classmethod
    def extract_all_from_x509(cls, cert: x509.Certificate) -> dict[str, Any]:
        """Extract all fields from a ``cryptography`` X.509 certificate object."""
        result: dict[str, Any] = {}

        cns = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if cns:
            result["ssl_subject_cn"] = cns[0].value

        orgs = cert.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
        if orgs:
            result["ssl_issuer"] = orgs[0].value
        issuer_cns = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
        if issuer_cns:
            result["ssl_issuer_cn"] = issuer_cns[0].value

        result["ssl_expires"] = int(calendar.timegm(cert.not_valid_after_utc.timetuple()))
        result["ssl_not_before"] = int(calendar.timegm(cert.not_valid_before_utc.timetuple()))

        try:
            san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            dns_names = san_ext.value.get_values_for_type(x509.DNSName)
            if dns_names:
                result["ssl_san"] = dns_names
        except x509.ExtensionNotFound:
            pass

        result["ssl_serial"] = format(cert.serial_number, "X")
        result["ssl_version"] = cert.version.value

        return result


class Nip66SslMetadata(BaseNipMetadata):
    """Container for SSL/TLS certificate data and inspection logs.

    Provides the ``execute()`` class method that performs certificate
    extraction and chain validation against a relay's TLS endpoint.

    Warning:
        The certificate extraction phase uses ``CERT_NONE`` to read
        certificates from relays with invalid chains. This is intentional
        for monitoring purposes and does not affect the ``ssl_valid`` field,
        which is determined by a separate validating connection.

    See Also:
        [bigbrotr.nips.nip66.nip66.Nip66][bigbrotr.nips.nip66.nip66.Nip66]:
            Top-level model that orchestrates this alongside other tests.
        [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
            The ``NIP66_SSL`` variant used when storing these results.
        [bigbrotr.nips.nip66.rtt.Nip66RttMetadata][bigbrotr.nips.nip66.rtt.Nip66RttMetadata]:
            RTT test that also involves SSL connections.
    """

    data: Nip66SslData
    logs: Nip66SslLogs

    @staticmethod
    def _ssl(host: str, port: int, timeout: float) -> dict[str, Any]:
        """Perform synchronous certificate extraction and validation.

        First extracts certificate data using a non-validating context,
        then separately validates the certificate chain using a default
        (validating) context.

        Args:
            host: Hostname to connect to.
            port: TCP port number.
            timeout: Socket timeout in seconds.

        Returns:
            Dictionary of extracted SSL fields including ``ssl_valid``.
        """
        result: dict[str, Any] = {}
        result.update(Nip66SslMetadata._extract_certificate_data(host, port, timeout))
        result["ssl_valid"] = Nip66SslMetadata._validate_certificate(host, port, timeout)
        return result

    @staticmethod
    def _extract_certificate_data(host: str, port: int, timeout: float) -> dict[str, Any]:
        """Extract certificate fields using a non-validating SSL context.

        Uses ``CERT_NONE`` so the certificate can be read even when the
        chain is invalid or self-signed.  The DER-encoded certificate is
        parsed via the ``cryptography`` library because
        ``getpeercert()`` (dict form) returns an empty dict with
        ``CERT_NONE``.
        """
        result: dict[str, Any] = {}
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        try:
            with (
                socket.create_connection((host, port), timeout=timeout) as sock,
                context.wrap_socket(sock, server_hostname=host) as ssock,
            ):
                cert_binary = ssock.getpeercert(binary_form=True)

                if cert_binary:
                    result["ssl_fingerprint"] = CertificateExtractor.extract_fingerprint(
                        cert_binary
                    )
                    parsed = x509.load_der_x509_certificate(cert_binary)
                    result.update(CertificateExtractor.extract_all_from_x509(parsed))

                result.update(Nip66SslMetadata._extract_tls_info(ssock))

        except ssl.SSLError as e:
            logger.debug("ssl_cert_extraction_failed error=%s", str(e))
        except OSError as e:
            logger.debug("ssl_cert_extraction_error error=%s", str(e))

        return result

    @staticmethod
    def _extract_tls_info(ssock: ssl.SSLSocket) -> dict[str, Any]:
        """Extract the negotiated TLS protocol version and cipher details."""
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
        """Validate the certificate chain using the system trust store.

        Returns:
            True if the certificate passes full chain verification.
        """
        try:
            verify_context = ssl.create_default_context()
            with (
                socket.create_connection((host, port), timeout=timeout) as sock,
                verify_context.wrap_socket(sock, server_hostname=host),
            ):
                return True
        except ssl.SSLError:
            return False
        except OSError as e:
            logger.debug("ssl_validation_error error=%s", str(e))
            return False

    @classmethod
    async def execute(
        cls,
        relay: Relay,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> Self:
        """Inspect the SSL/TLS certificate of a clearnet relay.

        Runs the synchronous SSL operations in a thread pool to avoid
        blocking the event loop.

        Args:
            relay: Clearnet relay to inspect.
            timeout: Socket timeout in seconds (default: 10.0).

        Returns:
            An ``Nip66SslMetadata`` instance with certificate data and logs.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("ssl_testing relay=%s timeout_s=%s", relay.url, timeout)

        if relay.network != NetworkType.CLEARNET:
            return cls(
                data=Nip66SslData(),
                logs=Nip66SslLogs(
                    success=False, reason=f"requires clearnet, got {relay.network.value}"
                ),
            )

        data: dict[str, Any] = {}
        logs: dict[str, Any] = {"success": False, "reason": None}
        port = relay.port or 443

        try:
            logger.debug("ssl_checking host=%s port=%s", relay.host, port)
            data = await asyncio.to_thread(cls._ssl, relay.host, port, timeout)
            if data:
                logs["success"] = True
                logger.debug("ssl_checked relay=%s valid=%s", relay.url, data.get("ssl_valid"))
            else:
                logs["reason"] = "no certificate data extracted"
                logger.debug("ssl_no_data relay=%s", relay.url)
        except OSError as e:
            logs["reason"] = str(e) or type(e).__name__
            logger.debug("ssl_error relay=%s error=%s", relay.url, str(e))

        return cls(
            data=Nip66SslData.model_validate(Nip66SslData.parse(data)),
            logs=Nip66SslLogs.model_validate(logs),
        )
