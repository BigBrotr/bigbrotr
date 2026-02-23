"""
Unit tests for models.nips.nip66.ssl module.

Tests:
- CertificateExtractor.extract_subject_cn() - subject Common Name
- CertificateExtractor.extract_issuer() - issuer organization and CN
- CertificateExtractor.extract_validity() - notAfter, notBefore dates
- CertificateExtractor.extract_san() - Subject Alternative Names
- CertificateExtractor.extract_serial_and_version() - serial number and version
- CertificateExtractor.extract_fingerprint() - SHA-256 fingerprint
- CertificateExtractor.extract_all() - combines all extraction methods
- Nip66SslMetadata._ssl() - synchronous SSL check
- Nip66SslMetadata.execute() - async SSL check with clearnet validation
"""

from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import MagicMock, patch

from bigbrotr.models import Relay
from bigbrotr.nips.nip66.ssl import CertificateExtractor, Nip66SslMetadata


class TestCertificateExtractorExtractSubjectCn:
    """Test CertificateExtractor.extract_subject_cn() method."""

    def test_extracts_common_name(self) -> None:
        """Extract commonName from subject."""
        cert: dict[str, Any] = {
            "subject": ((("commonName", "relay.example.com"),),),
        }
        result = CertificateExtractor.extract_subject_cn(cert)
        assert result == "relay.example.com"

    def test_extracts_from_nested_rdn(self) -> None:
        """Extract commonName from nested RDN structure."""
        cert: dict[str, Any] = {
            "subject": (
                (("organizationName", "Example Inc"),),
                (("commonName", "relay.example.com"),),
            ),
        }
        result = CertificateExtractor.extract_subject_cn(cert)
        assert result == "relay.example.com"

    def test_returns_none_when_no_common_name(self) -> None:
        """Return None when commonName is not present."""
        cert: dict[str, Any] = {
            "subject": ((("organizationName", "Example Inc"),),),
        }
        result = CertificateExtractor.extract_subject_cn(cert)
        assert result is None

    def test_returns_none_for_empty_subject(self) -> None:
        """Return None for empty subject."""
        cert: dict[str, Any] = {"subject": ()}
        result = CertificateExtractor.extract_subject_cn(cert)
        assert result is None

    def test_returns_none_when_subject_missing(self) -> None:
        """Return None when subject key is missing."""
        cert: dict[str, Any] = {}
        result = CertificateExtractor.extract_subject_cn(cert)
        assert result is None


class TestCertificateExtractorExtractIssuer:
    """Test CertificateExtractor.extract_issuer() method."""

    def test_extracts_issuer_org_and_cn(self) -> None:
        """Extract both organizationName and commonName from issuer."""
        cert: dict[str, Any] = {
            "issuer": (
                (("organizationName", "Let's Encrypt"),),
                (("commonName", "R3"),),
            ),
        }
        result = CertificateExtractor.extract_issuer(cert)
        assert result["ssl_issuer"] == "Let's Encrypt"
        assert result["ssl_issuer_cn"] == "R3"

    def test_extracts_only_org(self) -> None:
        """Extract only organizationName when CN is missing."""
        cert: dict[str, Any] = {
            "issuer": ((("organizationName", "DigiCert"),),),
        }
        result = CertificateExtractor.extract_issuer(cert)
        assert result["ssl_issuer"] == "DigiCert"
        assert "ssl_issuer_cn" not in result

    def test_extracts_only_cn(self) -> None:
        """Extract only commonName when org is missing."""
        cert: dict[str, Any] = {
            "issuer": ((("commonName", "Root CA"),),),
        }
        result = CertificateExtractor.extract_issuer(cert)
        assert result["ssl_issuer_cn"] == "Root CA"
        assert "ssl_issuer" not in result

    def test_returns_empty_for_empty_issuer(self) -> None:
        """Return empty dict for empty issuer."""
        cert: dict[str, Any] = {"issuer": ()}
        result = CertificateExtractor.extract_issuer(cert)
        assert result == {}

    def test_returns_empty_when_issuer_missing(self) -> None:
        """Return empty dict when issuer key is missing."""
        cert: dict[str, Any] = {}
        result = CertificateExtractor.extract_issuer(cert)
        assert result == {}


class TestCertificateExtractorExtractValidity:
    """Test CertificateExtractor.extract_validity() method."""

    def test_extracts_expiration_date(self) -> None:
        """Extract ssl_expires from notAfter."""
        cert: dict[str, Any] = {
            "notAfter": "Dec 31 23:59:59 2024 GMT",
        }
        result = CertificateExtractor.extract_validity(cert)
        assert "ssl_expires" in result
        assert isinstance(result["ssl_expires"], (int, float))

    def test_extracts_not_before_date(self) -> None:
        """Extract ssl_not_before from notBefore."""
        cert: dict[str, Any] = {
            "notBefore": "Jan  1 00:00:00 2024 GMT",
        }
        result = CertificateExtractor.extract_validity(cert)
        assert "ssl_not_before" in result
        assert isinstance(result["ssl_not_before"], (int, float))

    def test_extracts_both_dates(self) -> None:
        """Extract both notAfter and notBefore."""
        cert: dict[str, Any] = {
            "notAfter": "Dec 31 23:59:59 2024 GMT",
            "notBefore": "Jan  1 00:00:00 2024 GMT",
        }
        result = CertificateExtractor.extract_validity(cert)
        assert "ssl_expires" in result
        assert "ssl_not_before" in result
        assert result["ssl_expires"] > result["ssl_not_before"]

    def test_returns_empty_when_dates_missing(self) -> None:
        """Return empty dict when dates are missing."""
        cert: dict[str, Any] = {}
        result = CertificateExtractor.extract_validity(cert)
        assert result == {}

    def test_handles_none_values(self) -> None:
        """Handle None values gracefully."""
        cert: dict[str, Any] = {"notAfter": None, "notBefore": None}
        result = CertificateExtractor.extract_validity(cert)
        assert result == {}


class TestCertificateExtractorExtractSan:
    """Test CertificateExtractor.extract_san() method."""

    def test_extracts_dns_entries(self) -> None:
        """Extract DNS entries from SAN."""
        cert: dict[str, Any] = {
            "subjectAltName": (
                ("DNS", "relay.example.com"),
                ("DNS", "*.example.com"),
            ),
        }
        result = CertificateExtractor.extract_san(cert)
        assert result == ["relay.example.com", "*.example.com"]

    def test_filters_non_dns_entries(self) -> None:
        """Filter out non-DNS entries from SAN."""
        cert: dict[str, Any] = {
            "subjectAltName": (
                ("DNS", "relay.example.com"),
                ("IP Address", "8.8.8.8"),
                ("DNS", "www.example.com"),
            ),
        }
        result = CertificateExtractor.extract_san(cert)
        assert result == ["relay.example.com", "www.example.com"]

    def test_returns_none_for_empty_san(self) -> None:
        """Return None for empty SAN."""
        cert: dict[str, Any] = {"subjectAltName": ()}
        result = CertificateExtractor.extract_san(cert)
        assert result is None

    def test_returns_none_when_san_missing(self) -> None:
        """Return None when subjectAltName key is missing."""
        cert: dict[str, Any] = {}
        result = CertificateExtractor.extract_san(cert)
        assert result is None

    def test_filters_non_string_dns_values(self) -> None:
        """Filter out non-string DNS values."""
        cert: dict[str, Any] = {
            "subjectAltName": (
                ("DNS", "relay.example.com"),
                ("DNS", 12345),  # Invalid
                ("DNS", "www.example.com"),
            ),
        }
        result = CertificateExtractor.extract_san(cert)
        assert result == ["relay.example.com", "www.example.com"]


class TestCertificateExtractorExtractSerialAndVersion:
    """Test CertificateExtractor.extract_serial_and_version() method."""

    def test_extracts_serial_number(self) -> None:
        """Extract serial number."""
        cert: dict[str, Any] = {"serialNumber": "04ABCDEF12345678"}
        result = CertificateExtractor.extract_serial_and_version(cert)
        assert result["ssl_serial"] == "04ABCDEF12345678"

    def test_extracts_version(self) -> None:
        """Extract certificate version."""
        cert: dict[str, Any] = {"version": 3}
        result = CertificateExtractor.extract_serial_and_version(cert)
        assert result["ssl_version"] == 3

    def test_extracts_both(self) -> None:
        """Extract both serial and version."""
        cert: dict[str, Any] = {"serialNumber": "ABCD1234", "version": 3}
        result = CertificateExtractor.extract_serial_and_version(cert)
        assert result["ssl_serial"] == "ABCD1234"
        assert result["ssl_version"] == 3

    def test_handles_version_zero(self) -> None:
        """Handle version 0 (should be included)."""
        cert: dict[str, Any] = {"version": 0}
        result = CertificateExtractor.extract_serial_and_version(cert)
        assert result["ssl_version"] == 0

    def test_returns_empty_when_missing(self) -> None:
        """Return empty dict when both are missing."""
        cert: dict[str, Any] = {}
        result = CertificateExtractor.extract_serial_and_version(cert)
        assert result == {}


class TestCertificateExtractorExtractFingerprint:
    """Test CertificateExtractor.extract_fingerprint() method."""

    def test_computes_sha256_fingerprint(self) -> None:
        """Compute SHA-256 fingerprint from binary certificate."""
        cert_binary = b"test certificate data"
        result = CertificateExtractor.extract_fingerprint(cert_binary)

        # Verify format
        assert result.startswith("SHA256:")
        assert ":" in result[7:]  # Colon-separated hex

    def test_fingerprint_format(self) -> None:
        """Verify fingerprint format is SHA256:XX:XX:..."""
        cert_binary = b"test"
        result = CertificateExtractor.extract_fingerprint(cert_binary)

        # Format should be SHA256: followed by colon-separated uppercase hex
        parts = result.split(":")
        assert parts[0] == "SHA256"
        assert len(parts) == 33  # SHA256: + 32 pairs of hex digits

        # Each part after SHA256 should be 2 hex chars
        for part in parts[1:]:
            assert len(part) == 2
            assert all(c in "0123456789ABCDEF" for c in part)

    def test_fingerprint_matches_manual_calculation(self) -> None:
        """Fingerprint matches manual SHA-256 calculation."""
        cert_binary = b"hello world"
        result = CertificateExtractor.extract_fingerprint(cert_binary)

        # Calculate expected fingerprint
        digest = hashlib.sha256(cert_binary).hexdigest().upper()
        expected = "SHA256:" + ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))

        assert result == expected


class TestCertificateExtractorExtractAll:
    """Test CertificateExtractor.extract_all() method."""

    def test_combines_all_extraction_methods(
        self,
        mock_certificate_dict: dict[str, Any],
    ) -> None:
        """extract_all combines all certificate fields."""
        result = CertificateExtractor.extract_all(mock_certificate_dict)

        assert result["ssl_subject_cn"] == "relay.example.com"
        assert result["ssl_issuer"] == "Let's Encrypt"
        assert result["ssl_issuer_cn"] == "R3"
        assert "ssl_expires" in result
        assert "ssl_not_before" in result
        assert result["ssl_san"] == ["relay.example.com", "*.example.com"]
        assert result["ssl_serial"] == "04ABCDEF12345678"
        assert result["ssl_version"] == 3

    def test_empty_cert_returns_empty_dict(self) -> None:
        """Empty certificate returns empty dict."""
        result = CertificateExtractor.extract_all({})
        assert result == {}

    def test_partial_cert_data(self) -> None:
        """Handle certificate with partial data."""
        cert: dict[str, Any] = {
            "subject": ((("commonName", "test.com"),),),
            "version": 3,
        }
        result = CertificateExtractor.extract_all(cert)
        assert result["ssl_subject_cn"] == "test.com"
        assert result["ssl_version"] == 3
        assert "ssl_issuer" not in result


class TestNip66SslMetadataSslSync:
    """Test Nip66SslMetadata._ssl() synchronous method."""

    def test_success_returns_valid_cert(
        self,
        mock_certificate_binary: bytes,
    ) -> None:
        """Successful SSL check returns ssl_valid=True and cert info."""
        mock_x509_cert = MagicMock()
        cn_attr = MagicMock()
        cn_attr.value = "relay.example.com"
        mock_x509_cert.subject.get_attributes_for_oid.return_value = [cn_attr]

        issuer_org = MagicMock()
        issuer_org.value = "Let's Encrypt"
        issuer_cn = MagicMock()
        issuer_cn.value = "R3"

        def issuer_attrs(oid: Any) -> list[Any]:
            from cryptography.x509.oid import NameOID

            if oid == NameOID.ORGANIZATION_NAME:
                return [issuer_org]
            if oid == NameOID.COMMON_NAME:
                return [issuer_cn]
            return []

        mock_x509_cert.issuer.get_attributes_for_oid.side_effect = issuer_attrs

        from datetime import UTC, datetime

        mock_x509_cert.not_valid_after_utc = datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
        mock_x509_cert.not_valid_before_utc = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        san_ext = MagicMock()
        san_ext.value.get_values_for_type.return_value = ["relay.example.com", "*.example.com"]
        mock_x509_cert.extensions.get_extension_for_class.return_value = san_ext

        mock_x509_cert.serial_number = 0x04ABCDEF12345678
        mock_x509_cert.version = MagicMock(value=3)

        with (
            patch("socket.create_connection") as mock_conn,
            patch("ssl.create_default_context") as mock_ctx,
            patch(
                "bigbrotr.nips.nip66.ssl.x509.load_der_x509_certificate",
                return_value=mock_x509_cert,
            ),
        ):
            mock_socket = MagicMock()
            mock_conn.return_value.__enter__.return_value = mock_socket
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            mock_ssl_socket = MagicMock()
            mock_ssl_socket.getpeercert.return_value = mock_certificate_binary
            mock_ssl_socket.version.return_value = "TLSv1.3"
            mock_ssl_socket.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)

            mock_wrapped = MagicMock()
            mock_wrapped.__enter__.return_value = mock_ssl_socket
            mock_wrapped.__exit__ = MagicMock(return_value=False)
            mock_ctx.return_value.wrap_socket.return_value = mock_wrapped

            result = Nip66SslMetadata._ssl("example.com", 443, 30.0)

        assert result["ssl_valid"] is True
        assert result.get("ssl_subject_cn") == "relay.example.com"
        assert result.get("ssl_issuer") == "Let's Encrypt"
        assert result.get("ssl_issuer_cn") == "R3"
        assert result.get("ssl_protocol") == "TLSv1.3"
        assert result.get("ssl_cipher") == "TLS_AES_256_GCM_SHA384"
        assert result.get("ssl_cipher_bits") == 256
        assert result.get("ssl_san") == ["relay.example.com", "*.example.com"]

    def test_ssl_error_returns_invalid(self) -> None:
        """SSL error returns ssl_valid=False."""
        import ssl as ssl_module

        with patch("socket.create_connection") as mock_conn:
            mock_socket = MagicMock()
            mock_conn.return_value.__enter__.return_value = mock_socket
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            with patch("ssl.create_default_context") as mock_ctx:
                mock_ctx.return_value.wrap_socket.side_effect = ssl_module.SSLError()
                result = Nip66SslMetadata._ssl("example.com", 443, 30.0)

        assert result.get("ssl_valid") is False

    def test_connection_error_returns_invalid(self) -> None:
        """Connection error returns ssl_valid=False."""
        with patch("socket.create_connection", side_effect=TimeoutError()):
            result = Nip66SslMetadata._ssl("example.com", 443, 30.0)

        assert result.get("ssl_valid") is False


class TestNip66SslMetadataSslAsync:
    """Test Nip66SslMetadata.execute() async class method."""

    async def test_clearnet_wss_returns_ssl_metadata(self, relay: Relay) -> None:
        """Returns Nip66SslMetadata for clearnet wss:// relay."""
        ssl_result = {
            "ssl_valid": True,
            "ssl_issuer": "Test CA",
            "ssl_protocol": "TLSv1.3",
        }

        with patch.object(Nip66SslMetadata, "_ssl", return_value=ssl_result):
            result = await Nip66SslMetadata.execute(relay, 10.0)

        assert isinstance(result, Nip66SslMetadata)
        assert result.data.ssl_valid is True
        assert result.data.ssl_protocol == "TLSv1.3"
        assert result.logs.success is True

    async def test_ssl_failure_returns_metadata_with_failure(self, relay: Relay) -> None:
        """SSL check failure returns Nip66SslMetadata with success=False."""
        with patch.object(Nip66SslMetadata, "_ssl", return_value={}):
            result = await Nip66SslMetadata.execute(relay, 10.0)

        assert isinstance(result, Nip66SslMetadata)
        assert result.logs.success is False
        assert result.logs.reason is not None

    async def test_tor_returns_failure(self, tor_relay: Relay) -> None:
        """Returns failure for Tor relay (SSL not applicable)."""
        result = await Nip66SslMetadata.execute(tor_relay, 10.0)
        assert result.logs.success is False
        assert "requires clearnet" in result.logs.reason

    async def test_i2p_returns_failure(self, i2p_relay: Relay) -> None:
        """Returns failure for I2P relay (SSL not applicable)."""
        result = await Nip66SslMetadata.execute(i2p_relay, 10.0)
        assert result.logs.success is False
        assert "requires clearnet" in result.logs.reason

    async def test_loki_returns_failure(self, loki_relay: Relay) -> None:
        """Returns failure for Lokinet relay (SSL not applicable)."""
        result = await Nip66SslMetadata.execute(loki_relay, 10.0)
        assert result.logs.success is False
        assert "requires clearnet" in result.logs.reason

    async def test_uses_default_port_443(self, relay: Relay) -> None:
        """Uses port 443 when relay has no explicit port."""
        ssl_result = {"ssl_valid": True}

        with patch.object(Nip66SslMetadata, "_ssl", return_value=ssl_result) as mock_ssl:
            await Nip66SslMetadata.execute(relay, 10.0)

        mock_ssl.assert_called_once()
        call_args = mock_ssl.call_args
        assert call_args[0][1] == 443

    async def test_uses_explicit_port(self, relay_with_port: Relay) -> None:
        """Uses explicit port when relay specifies one."""
        ssl_result = {"ssl_valid": True}

        with patch.object(Nip66SslMetadata, "_ssl", return_value=ssl_result) as mock_ssl:
            await Nip66SslMetadata.execute(relay_with_port, 10.0)

        mock_ssl.assert_called_once()
        call_args = mock_ssl.call_args
        assert call_args[0][1] == 8443

    async def test_exception_returns_failure(self, relay: Relay) -> None:
        """Exception during SSL check returns failure logs."""
        with patch.object(Nip66SslMetadata, "_ssl", side_effect=OSError("Network error")):
            result = await Nip66SslMetadata.execute(relay, 10.0)

        assert isinstance(result, Nip66SslMetadata)
        assert result.logs.success is False
        assert "Network error" in result.logs.reason

    async def test_default_timeout_used(self, relay: Relay) -> None:
        """Uses default timeout when None provided."""
        ssl_result = {"ssl_valid": True}

        with patch.object(Nip66SslMetadata, "_ssl", return_value=ssl_result) as mock_ssl:
            await Nip66SslMetadata.execute(relay, None)

        mock_ssl.assert_called_once()
        call_args = mock_ssl.call_args
        assert call_args[0][2] > 0
