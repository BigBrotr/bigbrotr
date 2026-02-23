"""Unit tests for nips.event_builders module.

Tests Nostr event building and tag construction with typed NIP data models.
Covers Kind 0 (NIP-01), Kind 10166, Kind 30166, and all tag builder functions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bigbrotr.models.constants import NetworkType
from bigbrotr.nips.event_builders import (
    AccessFlags,
    add_geo_tags,
    add_language_tags,
    add_net_tags,
    add_nip11_tags,
    add_requirement_and_type_tags,
    add_rtt_tags,
    add_ssl_tags,
    add_type_tags,
    build_monitor_announcement,
    build_profile_event,
    build_relay_discovery,
)
from bigbrotr.nips.nip11 import Nip11Selection
from bigbrotr.nips.nip11.data import Nip11InfoData, Nip11InfoDataLimitation
from bigbrotr.nips.nip66 import Nip66Selection
from bigbrotr.nips.nip66.data import Nip66GeoData, Nip66NetData, Nip66RttData, Nip66SslData
from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs


if TYPE_CHECKING:
    from nostr_sdk import Tag


# ============================================================================
# Helpers
# ============================================================================


def _extract_tag_map(tags: list[Tag]) -> dict[str, str]:
    """Convert tags to a {key: first_value} mapping (single-value tags only)."""
    return {t.as_vec()[0]: t.as_vec()[1] for t in tags if len(t.as_vec()) >= 2}


def _extract_tag_pairs(tags: list[Tag]) -> list[tuple[str, str]]:
    """Convert tags to a list of (key, first_value) tuples."""
    return [(t.as_vec()[0], t.as_vec()[1]) for t in tags if len(t.as_vec()) >= 2]


def _extract_tag_vecs(tags: list[Tag]) -> list[list[str]]:
    """Convert a list of nostr_sdk Tags to their vector representation."""
    return [t.as_vec() for t in tags]


# ============================================================================
# build_profile_event (Kind 0)
# ============================================================================


class TestBuildProfileEvent:
    """Tests for build_profile_event()."""

    def test_all_fields(self) -> None:
        """Test Kind 0 builder with all profile fields populated."""
        builder = build_profile_event(
            name="BigBrotr",
            about="A monitor",
            picture="https://example.com/pic.png",
            nip05="monitor@example.com",
            website="https://example.com",
            banner="https://example.com/banner.png",
            lud16="monitor@ln.example.com",
        )
        assert builder is not None

    def test_minimal_fields(self) -> None:
        """Test Kind 0 builder with only name field set."""
        builder = build_profile_event(name="MinimalMonitor")
        assert builder is not None

    def test_no_fields(self) -> None:
        """Test Kind 0 builder with no profile fields set."""
        builder = build_profile_event()
        assert builder is not None


# ============================================================================
# build_monitor_announcement (Kind 10166)
# ============================================================================


class TestBuildMonitorAnnouncement:
    """Tests for build_monitor_announcement()."""

    def test_all_checks_enabled(self) -> None:
        """Test Kind 10166 builder with all NIP-66 checks enabled."""
        builder = build_monitor_announcement(
            interval=3600,
            timeout_ms=10000,
            enabled_networks=[NetworkType.CLEARNET],
            nip11_selection=Nip11Selection(info=True),
            nip66_selection=Nip66Selection(rtt=True, ssl=True, geo=True, net=True),
        )
        assert builder is not None

    def test_subset_checks(self) -> None:
        """Test Kind 10166 builder with only RTT and NIP-11 enabled."""
        builder = build_monitor_announcement(
            interval=1800,
            timeout_ms=5000,
            enabled_networks=[NetworkType.CLEARNET, NetworkType.TOR],
            nip11_selection=Nip11Selection(info=True),
            nip66_selection=Nip66Selection(
                rtt=True,
                ssl=False,
                geo=False,
                net=False,
                dns=False,
                http=False,
            ),
        )
        assert builder is not None

    def test_no_checks(self) -> None:
        """Test Kind 10166 builder with all checks disabled."""
        builder = build_monitor_announcement(
            interval=600,
            timeout_ms=10000,
            enabled_networks=[NetworkType.CLEARNET],
            nip11_selection=Nip11Selection(info=False),
            nip66_selection=Nip66Selection(
                rtt=False,
                ssl=False,
                geo=False,
                net=False,
                dns=False,
                http=False,
            ),
        )
        assert builder is not None


# ============================================================================
# add_rtt_tags
# ============================================================================


class TestAddRttTags:
    """Tests for add_rtt_tags()."""

    def test_with_data(self) -> None:
        """Test RTT tags are added when data is present."""
        tags: list[Tag] = []
        add_rtt_tags(tags, Nip66RttData(rtt_open=45, rtt_read=120, rtt_write=85))

        tag_map = _extract_tag_map(tags)
        assert tag_map["rtt-open"] == "45"
        assert tag_map["rtt-read"] == "120"
        assert tag_map["rtt-write"] == "85"

    def test_partial_data(self) -> None:
        """Test RTT tags with only rtt_open present."""
        tags: list[Tag] = []
        add_rtt_tags(tags, Nip66RttData(rtt_open=30))

        tag_map = _extract_tag_map(tags)
        assert tag_map["rtt-open"] == "30"
        assert "rtt-read" not in tag_map
        assert "rtt-write" not in tag_map

    def test_none_data(self) -> None:
        """Test RTT tags when data is None."""
        tags: list[Tag] = []
        add_rtt_tags(tags, None)
        assert tags == []

    def test_empty_data(self) -> None:
        """Test RTT tags when all fields are None."""
        tags: list[Tag] = []
        add_rtt_tags(tags, Nip66RttData())
        assert tags == []


# ============================================================================
# add_ssl_tags
# ============================================================================


class TestAddSslTags:
    """Tests for add_ssl_tags()."""

    def test_valid_cert(self) -> None:
        """Test SSL tags with valid certificate data."""
        tags: list[Tag] = []
        add_ssl_tags(
            tags,
            Nip66SslData(
                ssl_valid=True,
                ssl_expires=1735689600,
                ssl_issuer="Let's Encrypt",
            ),
        )

        tag_map = _extract_tag_map(tags)
        assert tag_map["ssl"] == "valid"
        assert tag_map["ssl-expires"] == "1735689600"
        assert tag_map["ssl-issuer"] == "Let's Encrypt"

    def test_invalid_cert(self) -> None:
        """Test SSL tags with invalid certificate."""
        tags: list[Tag] = []
        add_ssl_tags(tags, Nip66SslData(ssl_valid=False, ssl_expires=1600000000))

        tag_map = _extract_tag_map(tags)
        assert tag_map["ssl"] == "!valid"
        assert tag_map["ssl-expires"] == "1600000000"
        assert "ssl-issuer" not in tag_map

    def test_missing_fields(self) -> None:
        """Test SSL tags when only ssl_valid is present."""
        tags: list[Tag] = []
        add_ssl_tags(tags, Nip66SslData(ssl_valid=True))

        tag_map = _extract_tag_map(tags)
        assert tag_map["ssl"] == "valid"
        assert "ssl-expires" not in tag_map
        assert "ssl-issuer" not in tag_map

    def test_none_data(self) -> None:
        """Test SSL tags when data is None."""
        tags: list[Tag] = []
        add_ssl_tags(tags, None)
        assert tags == []


# ============================================================================
# add_net_tags
# ============================================================================


class TestAddNetTags:
    """Tests for add_net_tags()."""

    def test_all_fields(self) -> None:
        """Test net tags with all fields present."""
        tags: list[Tag] = []
        add_net_tags(
            tags,
            Nip66NetData(
                net_ip="1.2.3.4",
                net_ipv6="2001:db8::1",
                net_asn=13335,
                net_asn_org="Cloudflare",
            ),
        )

        tag_map = _extract_tag_map(tags)
        assert tag_map["net-ip"] == "1.2.3.4"
        assert tag_map["net-ipv6"] == "2001:db8::1"
        assert tag_map["net-asn"] == "13335"
        assert tag_map["net-asn-org"] == "Cloudflare"

    def test_partial_fields(self) -> None:
        """Test net tags with only IP and ASN present."""
        tags: list[Tag] = []
        add_net_tags(tags, Nip66NetData(net_ip="8.8.8.8", net_asn=15169))

        tag_map = _extract_tag_map(tags)
        assert tag_map["net-ip"] == "8.8.8.8"
        assert tag_map["net-asn"] == "15169"
        assert "net-ipv6" not in tag_map
        assert "net-asn-org" not in tag_map

    def test_none_data(self) -> None:
        """Test net tags when data is None."""
        tags: list[Tag] = []
        add_net_tags(tags, None)
        assert tags == []


# ============================================================================
# add_geo_tags
# ============================================================================


class TestAddGeoTags:
    """Tests for add_geo_tags()."""

    def test_all_fields(self) -> None:
        """Test geo tags with all fields present."""
        tags: list[Tag] = []
        add_geo_tags(
            tags,
            Nip66GeoData(
                geo_hash="u33dc",
                geo_country="DE",
                geo_city="Frankfurt",
                geo_lat=50.1109,
                geo_lon=8.6821,
                geo_tz="Europe/Berlin",
            ),
        )

        tag_map = _extract_tag_map(tags)
        assert tag_map["g"] == "u33dc"
        assert tag_map["geo-country"] == "DE"
        assert tag_map["geo-city"] == "Frankfurt"
        assert tag_map["geo-lat"] == "50.1109"
        assert tag_map["geo-lon"] == "8.6821"
        assert tag_map["geo-tz"] == "Europe/Berlin"

    def test_partial_fields(self) -> None:
        """Test geo tags with only country and geohash present."""
        tags: list[Tag] = []
        add_geo_tags(tags, Nip66GeoData(geo_hash="abc", geo_country="US"))

        tag_map = _extract_tag_map(tags)
        assert tag_map["g"] == "abc"
        assert tag_map["geo-country"] == "US"
        assert "geo-city" not in tag_map
        assert "geo-lat" not in tag_map
        assert "geo-lon" not in tag_map
        assert "geo-tz" not in tag_map

    def test_none_data(self) -> None:
        """Test geo tags when data is None."""
        tags: list[Tag] = []
        add_geo_tags(tags, None)
        assert tags == []


# ============================================================================
# add_language_tags
# ============================================================================


class TestAddLanguageTags:
    """Tests for add_language_tags()."""

    def test_filtering(self) -> None:
        """Test language tags filter to ISO 639-1 (2-char) codes."""
        tags: list[Tag] = []
        add_language_tags(
            tags,
            Nip11InfoData(
                language_tags=["en", "de", "en-US", "fr-FR", "zz"],
            ),
        )

        tag_vecs = _extract_tag_vecs(tags)
        lang_primaries = [v[1] for v in tag_vecs if v[0] == "l"]
        assert "en" in lang_primaries
        assert "de" in lang_primaries
        assert "fr" in lang_primaries
        assert "zz" in lang_primaries

    def test_wildcard(self) -> None:
        """Test language tags are skipped when wildcard is present."""
        tags: list[Tag] = []
        add_language_tags(tags, Nip11InfoData(language_tags=["en", "*", "de"]))
        assert tags == []

    def test_dedup(self) -> None:
        """Test language tags deduplication of primary codes."""
        tags: list[Tag] = []
        add_language_tags(tags, Nip11InfoData(language_tags=["en", "en-US", "en-GB"]))

        tag_vecs = _extract_tag_vecs(tags)
        lang_primaries = [v[1] for v in tag_vecs if v[0] == "l"]
        assert lang_primaries == ["en"]

    def test_empty(self) -> None:
        """Test language tags with empty list."""
        tags: list[Tag] = []
        add_language_tags(tags, Nip11InfoData(language_tags=[]))
        assert tags == []

    def test_no_language_tags(self) -> None:
        """Test language tags when field is None."""
        tags: list[Tag] = []
        add_language_tags(tags, Nip11InfoData())
        assert tags == []

    def test_iso_639_1_label(self) -> None:
        """Test that language tags have ISO-639-1 as third element."""
        tags: list[Tag] = []
        add_language_tags(tags, Nip11InfoData(language_tags=["en"]))

        assert len(tags) == 1
        vec = tags[0].as_vec()
        assert vec == ["l", "en", "ISO-639-1"]


# ============================================================================
# add_requirement_and_type_tags
# ============================================================================


class TestAddRequirementAndTypeTags:
    """Tests for add_requirement_and_type_tags()."""

    def test_auth_from_nip11(self) -> None:
        """Test auth requirement from NIP-11 limitation."""
        tags: list[Tag] = []
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(auth_required=True))
        add_requirement_and_type_tags(tags, nip11, None)
        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs

    def test_auth_from_rtt_probe(self) -> None:
        """Test auth requirement detected from RTT probe write failure."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            write_success=False,
            write_reason="auth-required: NIP-42",
        )
        add_requirement_and_type_tags(tags, Nip11InfoData(), rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs

    def test_payment_from_nip11(self) -> None:
        """Test payment requirement from NIP-11 limitation."""
        tags: list[Tag] = []
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(payment_required=True))
        add_requirement_and_type_tags(tags, nip11, None)
        pairs = _extract_tag_pairs(tags)
        assert ("R", "payment") in pairs

    def test_payment_from_rtt_probe(self) -> None:
        """Test payment requirement detected from RTT probe write failure."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            write_success=False,
            write_reason="payment required",
        )
        add_requirement_and_type_tags(tags, Nip11InfoData(), rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "payment") in pairs

    def test_restricted_writes_from_nip11(self) -> None:
        """Test restricted_writes requirement from NIP-11."""
        tags: list[Tag] = []
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(restricted_writes=True))
        add_requirement_and_type_tags(tags, nip11, None)
        pairs = _extract_tag_pairs(tags)
        assert ("R", "writes") in pairs

    def test_writes_cleared_when_write_succeeds(self) -> None:
        """Test writes restriction is cleared when RTT probe write succeeds."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(open_success=True, write_success=True)
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(restricted_writes=True))
        add_requirement_and_type_tags(tags, nip11, rtt_logs)
        pairs = _extract_tag_pairs(tags)
        assert ("R", "!writes") in pairs

    def test_pow_requirement(self) -> None:
        """Test PoW requirement from NIP-11 limitation."""
        tags: list[Tag] = []
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(min_pow_difficulty=16))
        add_requirement_and_type_tags(tags, nip11, None)
        pairs = _extract_tag_pairs(tags)
        assert ("R", "pow") in pairs

    def test_no_pow_when_zero(self) -> None:
        """Test no PoW requirement when min_pow_difficulty is 0."""
        tags: list[Tag] = []
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(min_pow_difficulty=0))
        add_requirement_and_type_tags(tags, nip11, None)
        pairs = _extract_tag_pairs(tags)
        assert ("R", "!pow") in pairs

    def test_all_restrictions_false(self) -> None:
        """Test all restrictions are negated when no restrictions apply."""
        tags: list[Tag] = []
        add_requirement_and_type_tags(tags, Nip11InfoData(), None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "!auth") in pairs
        assert ("R", "!payment") in pairs
        assert ("R", "!writes") in pairs
        assert ("R", "!pow") in pairs

    def test_auth_and_payment_combined(self) -> None:
        """Test combined auth and payment requirements."""
        tags: list[Tag] = []
        nip11 = Nip11InfoData(
            limitation=Nip11InfoDataLimitation(auth_required=True, payment_required=True),
        )
        add_requirement_and_type_tags(tags, nip11, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs
        assert ("R", "payment") in pairs

    def test_read_auth_from_rtt_probe(self) -> None:
        """Test read_auth detection from RTT probe read failure with auth reason."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            read_success=False,
            read_reason="auth-required",
            write_success=False,
            write_reason="auth-required: NIP-42",
        )
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(auth_required=True))
        add_requirement_and_type_tags(tags, nip11, rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("T", "PrivateStorage") in pairs

    def test_probe_overrides_nip11_auth(self) -> None:
        """Test write probe success clears NIP-11 auth_required claim."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(open_success=True, write_success=True)
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(auth_required=True))
        add_requirement_and_type_tags(tags, nip11, rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "!auth") in pairs
        assert ("T", "PublicInbox") in pairs

    def test_probe_overrides_nip11_payment(self) -> None:
        """Test write probe success clears NIP-11 payment_required claim."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(open_success=True, write_success=True)
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(payment_required=True))
        add_requirement_and_type_tags(tags, nip11, rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "!payment") in pairs
        assert ("T", "PublicInbox") in pairs

    def test_probe_overrides_nip11_all_restrictions(self) -> None:
        """Test write probe success clears all NIP-11 restriction claims."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(open_success=True, write_success=True)
        nip11 = Nip11InfoData(
            limitation=Nip11InfoDataLimitation(
                auth_required=True,
                payment_required=True,
                restricted_writes=True,
            ),
        )
        add_requirement_and_type_tags(tags, nip11, rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "!auth") in pairs
        assert ("R", "!payment") in pairs
        assert ("R", "!writes") in pairs
        assert ("T", "PublicInbox") in pairs

    def test_probe_adds_restriction_nip11_doesnt_claim(self) -> None:
        """Test write probe failure adds auth even when NIP-11 claims no restrictions."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            write_success=False,
            write_reason="auth-required: NIP-42",
        )
        add_requirement_and_type_tags(tags, Nip11InfoData(), rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs

    def test_no_probe_falls_back_to_nip11(self) -> None:
        """Test NIP-11 restrictions are used when no RTT probe is available."""
        tags: list[Tag] = []
        nip11 = Nip11InfoData(
            limitation=Nip11InfoDataLimitation(auth_required=True, payment_required=True),
        )
        add_requirement_and_type_tags(tags, nip11, None)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs
        assert ("R", "payment") in pairs


# ============================================================================
# add_type_tags
# ============================================================================


class TestAddTypeTags:
    """Tests for add_type_tags()."""

    def test_search_type(self) -> None:
        """Test Search type tag when NIP-50 is supported."""
        tags: list[Tag] = []
        add_type_tags(tags, [50], AccessFlags(False, False, False, False))
        pairs = _extract_tag_pairs(tags)
        assert ("T", "Search") in pairs

    def test_community_type(self) -> None:
        """Test Community type tag when NIP-29 is supported."""
        tags: list[Tag] = []
        add_type_tags(tags, [29], AccessFlags(False, False, False, False))
        pairs = _extract_tag_pairs(tags)
        assert ("T", "Community") in pairs

    def test_blob_type(self) -> None:
        """Test Blob type tag when NIP-95 is supported."""
        tags: list[Tag] = []
        add_type_tags(tags, [95], AccessFlags(False, False, False, False))
        pairs = _extract_tag_pairs(tags)
        assert ("T", "Blob") in pairs

    def test_paid_type(self) -> None:
        """Test Paid type tag when payment is required."""
        tags: list[Tag] = []
        add_type_tags(
            tags,
            None,
            AccessFlags(payment=True, auth=False, writes=False, read_auth=False),
        )

        pairs = _extract_tag_pairs(tags)
        assert ("T", "Paid") in pairs
        assert ("T", "PublicOutbox") in pairs

    def test_public_inbox_type(self) -> None:
        """Test PublicInbox type tag for open relay with no restrictions."""
        tags: list[Tag] = []
        add_type_tags(tags, None, AccessFlags(False, False, False, False))
        pairs = _extract_tag_pairs(tags)
        assert ("T", "PublicInbox") in pairs

    def test_public_outbox_type_auth(self) -> None:
        """Test PublicOutbox type tag when auth is required (no read_auth)."""
        tags: list[Tag] = []
        add_type_tags(
            tags,
            None,
            AccessFlags(payment=False, auth=True, writes=False, read_auth=False),
        )
        pairs = _extract_tag_pairs(tags)
        assert ("T", "PublicOutbox") in pairs

    def test_public_outbox_type_writes(self) -> None:
        """Test PublicOutbox type tag when writes are restricted (no read_auth)."""
        tags: list[Tag] = []
        add_type_tags(
            tags,
            None,
            AccessFlags(payment=False, auth=False, writes=True, read_auth=False),
        )
        pairs = _extract_tag_pairs(tags)
        assert ("T", "PublicOutbox") in pairs

    def test_private_storage_type(self) -> None:
        """Test PrivateStorage type tag when read_auth and auth are both true."""
        tags: list[Tag] = []
        add_type_tags(
            tags,
            None,
            AccessFlags(payment=False, auth=True, writes=False, read_auth=True),
        )
        pairs = _extract_tag_pairs(tags)
        assert ("T", "PrivateStorage") in pairs

    def test_private_inbox_type(self) -> None:
        """Test PrivateInbox type tag when read_auth is true but auth is false."""
        tags: list[Tag] = []
        add_type_tags(
            tags,
            None,
            AccessFlags(payment=False, auth=False, writes=False, read_auth=True),
        )
        pairs = _extract_tag_pairs(tags)
        assert ("T", "PrivateInbox") in pairs

    def test_multiple_capability_types(self) -> None:
        """Test multiple capability-based type tags when multiple NIPs are supported."""
        tags: list[Tag] = []
        add_type_tags(tags, [29, 50, 95], AccessFlags(False, False, False, False))

        pairs = _extract_tag_pairs(tags)
        assert ("T", "Search") in pairs
        assert ("T", "Community") in pairs
        assert ("T", "Blob") in pairs
        assert ("T", "PublicInbox") in pairs

    def test_paid_search_relay(self) -> None:
        """Test combined Paid and Search type tags."""
        tags: list[Tag] = []
        add_type_tags(
            tags,
            [50],
            AccessFlags(payment=True, auth=False, writes=False, read_auth=False),
        )

        pairs = _extract_tag_pairs(tags)
        assert ("T", "Search") in pairs
        assert ("T", "Paid") in pairs
        assert ("T", "PublicOutbox") in pairs


# ============================================================================
# add_nip11_tags
# ============================================================================


class TestAddNip11Tags:
    """Tests for add_nip11_tags()."""

    def test_with_nips(self) -> None:
        """Test NIP-11 tags with supported_nips."""
        tags: list[Tag] = []
        add_nip11_tags(tags, Nip11InfoData(supported_nips=[1, 11, 42, 50]))

        pairs = _extract_tag_pairs(tags)
        nip_tags = [(k, v) for k, v in pairs if k == "N"]
        assert ("N", "1") in nip_tags
        assert ("N", "11") in nip_tags
        assert ("N", "42") in nip_tags
        assert ("N", "50") in nip_tags

    def test_with_topic_tags(self) -> None:
        """Test NIP-11 tags with topic (t) tags."""
        tags: list[Tag] = []
        add_nip11_tags(tags, Nip11InfoData(tags=["social", "bitcoin", "nostr"]))

        pairs = _extract_tag_pairs(tags)
        topic_tags = [(k, v) for k, v in pairs if k == "t"]
        assert ("t", "social") in topic_tags
        assert ("t", "bitcoin") in topic_tags
        assert ("t", "nostr") in topic_tags

    def test_with_languages(self) -> None:
        """Test NIP-11 tags with language_tags."""
        tags: list[Tag] = []
        add_nip11_tags(tags, Nip11InfoData(language_tags=["en", "de", "fr-FR"]))

        tag_vecs = _extract_tag_vecs(tags)
        lang_primaries = [v[1] for v in tag_vecs if v[0] == "l"]
        assert "en" in lang_primaries
        assert "de" in lang_primaries
        assert "fr" in lang_primaries

    def test_with_requirements(self) -> None:
        """Test NIP-11 tags add requirement (R) tags."""
        tags: list[Tag] = []
        add_nip11_tags(
            tags,
            Nip11InfoData(
                limitation=Nip11InfoDataLimitation(auth_required=True, payment_required=False),
            ),
        )

        pairs = _extract_tag_pairs(tags)
        req_tags = [(k, v) for k, v in pairs if k == "R"]
        assert ("R", "auth") in req_tags
        assert ("R", "!payment") in req_tags

    def test_none_data(self) -> None:
        """Test NIP-11 tags when data is None."""
        tags: list[Tag] = []
        add_nip11_tags(tags, None)
        assert tags == []

    def test_with_rtt_logs(self) -> None:
        """Test NIP-11 tags pass rtt_logs through to requirement tags."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            write_success=False,
            write_reason="auth-required: NIP-42",
        )
        add_nip11_tags(tags, Nip11InfoData(), rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs


# ============================================================================
# build_relay_discovery (Kind 30166)
# ============================================================================


class TestBuildRelayDiscovery:
    """Tests for build_relay_discovery()."""

    def test_full_event(self) -> None:
        """Test full Kind 30166 event construction with all metadata."""
        builder = build_relay_discovery(
            "wss://relay.example.com",
            "clearnet",
            '{"name":"Test Relay"}',
            rtt_data=Nip66RttData(rtt_open=45, rtt_read=120, rtt_write=85),
            ssl_data=Nip66SslData(ssl_valid=True, ssl_expires=1735689600),
            nip11_data=Nip11InfoData(supported_nips=[1, 11, 50], tags=["social"]),
        )
        assert builder is not None

    def test_minimal(self) -> None:
        """Test Kind 30166 event with no metadata."""
        builder = build_relay_discovery("wss://relay.example.com", "clearnet")
        assert builder is not None

    def test_tor_relay(self) -> None:
        """Test Kind 30166 uses the correct network value for Tor relays."""
        onion = "a" * 56
        builder = build_relay_discovery(f"ws://{onion}.onion", "tor")
        assert builder is not None

    def test_nip11_content(self) -> None:
        """Test that Kind 30166 content uses nip11_canonical_json."""
        builder = build_relay_discovery(
            "wss://relay.example.com",
            "clearnet",
            '{"name":"Test Relay"}',
        )
        assert builder is not None


# ============================================================================
# AccessFlags
# ============================================================================


class TestAccessFlags:
    """Tests for AccessFlags NamedTuple."""

    def test_creation(self) -> None:
        """Test AccessFlags creation with named fields."""
        flags = AccessFlags(payment=True, auth=False, writes=True, read_auth=False)
        assert flags.payment is True
        assert flags.auth is False
        assert flags.writes is True
        assert flags.read_auth is False

    def test_tuple_unpacking(self) -> None:
        """Test AccessFlags can be unpacked as a tuple."""
        flags = AccessFlags(True, False, True, False)
        payment, auth, _writes, _read_auth = flags
        assert payment is True
        assert auth is False


# ============================================================================
# Integration: end-to-end tag generation
# ============================================================================


class TestEndToEndTagGeneration:
    """Integration-style tests verifying complete tag generation flows."""

    def test_full_relay_with_all_metadata(self) -> None:
        """Test a relay with RTT, SSL, NIP-11 produces expected tag set."""
        builder = build_relay_discovery(
            "wss://relay.example.com",
            "clearnet",
            '{"name":"Production Relay"}',
            rtt_data=Nip66RttData(rtt_open=30, rtt_read=100, rtt_write=80),
            ssl_data=Nip66SslData(
                ssl_valid=True,
                ssl_expires=1735689600,
                ssl_issuer="Let's Encrypt",
            ),
            nip11_data=Nip11InfoData(
                name="Production Relay",
                supported_nips=[1, 11, 42, 50],
                tags=["social"],
                language_tags=["en", "de"],
                limitation=Nip11InfoDataLimitation(
                    auth_required=False,
                    payment_required=False,
                    restricted_writes=False,
                    min_pow_difficulty=0,
                ),
            ),
            rtt_logs=Nip66RttMultiPhaseLogs(open_success=True, write_success=True),
        )
        assert builder is not None

    def test_auth_required_relay_types(self) -> None:
        """Test that auth-required relay gets PublicOutbox type."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            write_success=False,
            write_reason="auth-required: NIP-42",
        )
        nip11 = Nip11InfoData(limitation=Nip11InfoDataLimitation(auth_required=True))
        add_requirement_and_type_tags(tags, nip11, rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "auth") in pairs
        assert ("T", "PublicOutbox") in pairs

    def test_payment_required_with_paid_write_reason(self) -> None:
        """Test payment detection from 'paid' keyword in write_reason."""
        tags: list[Tag] = []
        rtt_logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            write_success=False,
            write_reason="paid relay only",
        )
        add_requirement_and_type_tags(tags, Nip11InfoData(), rtt_logs)

        pairs = _extract_tag_pairs(tags)
        assert ("R", "payment") in pairs
        assert ("T", "Paid") in pairs
