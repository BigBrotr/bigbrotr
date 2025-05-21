from typing import Optional, List, Dict, Any
from relay import Relay
import json


class RelayMetadata:
    """
    Class to represent metadata associated with a NOSTR relay.

    Attributes:
    - relay: Relay, the relay object
    - generated_at: int, the timestamp when the metadata was generated
    - connection_success: bool, indicates if the connection to the relay was successful
    - nip11_success: bool, indicates if the NIP-11 metadata was successfully retrieved
    - openable: Optional[bool], indicates if the relay is openable
    - readable: Optional[bool], indicates if the relay is readable
    - writable: Optional[bool], indicates if the relay is writable
    - rtt_open: Optional[int], the round-trip time for the connection
    - rtt_read: Optional[int], the round-trip time for reading from the relay
    - rtt_write: Optional[int], the round-trip time for writing to the relay
    - name: Optional[str], the name of the relay
    - description: Optional[str], a description of the relay
    - banner: Optional[str], the URL of the banner image
    - icon: Optional[str], the URL of the icon image
    - pubkey: Optional[str], the public key of the relay
    - contact: Optional[str], the contact information for the relay
    - supported_nips: Optional[List[int]], a list of supported NIPs (NOSTR Improvement Possibilities)
    - software: Optional[str], the software used by the relay
    - version: Optional[str], the version of the software
    - privacy_policy: Optional[str], the URL of the privacy policy
    - terms_of_service: Optional[str], the URL of the terms of service
    - limitation: Optional[Dict[str, Any]], limitations of the relay
    - extra_fields: Optional[Dict[str, Any]], additional fields for custom metadata

    Methods:
    - __init__(self, ...) -> None: Initializes a RelayMetadata object.
    - __repr__(self) -> str: Returns a string representation of the RelayMetadata object.
    - to_dict(self) -> dict: Converts the RelayMetadata object to a dictionary.
    - from_dict(data: dict) -> RelayMetadata: Creates a RelayMetadata object from a dictionary.
    """

    def __init__(
        self,
        relay: Relay,
        generated_at: int,
        connection_success: bool,
        nip11_success: bool,
        openable: Optional[bool] = None,
        readable: Optional[bool] = None,
        writable: Optional[bool] = None,
        rtt_open: Optional[int] = None,
        rtt_read: Optional[int] = None,
        rtt_write: Optional[int] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        banner: Optional[str] = None,
        icon: Optional[str] = None,
        pubkey: Optional[str] = None,
        contact: Optional[str] = None,
        supported_nips: Optional[List[int]] = None,
        software: Optional[str] = None,
        version: Optional[str] = None,
        privacy_policy: Optional[str] = None,
        terms_of_service: Optional[str] = None,
        limitation: Optional[Dict[str, Any]] = None,
        extra_fields: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize a RelayMetadata object.

        Parameters:
        - relay: Relay, the relay object
        - generated_at: int, the timestamp when the metadata was generated
        - connection_success: bool, indicates if the connection to the relay was successful
        - nip11_success: bool, indicates if the NIP-11 metadata was successfully retrieved
        - openable: Optional[bool], indicates if the relay is openable
        - readable: Optional[bool], indicates if the relay is readable
        - writable: Optional[bool], indicates if the relay is writable
        - rtt_open: Optional[int], the round-trip time for the connection
        - rtt_read: Optional[int], the round-trip time for reading from the relay
        - rtt_write: Optional[int], the round-trip time for writing to the relay
        - name: Optional[str], the name of the relay
        - description: Optional[str], a description of the relay
        - banner: Optional[str], the URL of the banner image
        - icon: Optional[str], the URL of the icon image
        - pubkey: Optional[str], the public key of the relay
        - contact: Optional[str], the contact information for the relay
        - supported_nips: Optional[List[int|str]], a list of supported NIPs
        - software: Optional[str], the software used by the relay
        - version: Optional[str], the version of the software
        - privacy_policy: Optional[str], the URL of the privacy policy
        - terms_of_service: Optional[str], the URL of the terms of service
        - limitation: Optional[Dict[str, Any]], limitations of the relay
        - extra_fields: Optional[Dict[str, Any]], additional fields for custom metadata

        Example:
        >>> relay_metadata = RelayMetadata(
        ...     relay=Relay("wss://relay.example.com"),
        ...     generated_at=1612137600,
        ...     connection_success=True,
        ...     nip11_success=True,
        ...     openable=True,
        ...     readable=True,
        ...     writable=True,
        ...     rtt_open=100,
        ...     rtt_read=200,
        ...     rtt_write=300,
        ...     name="Example Relay",
        ...     description="An example NOSTR relay",
        ...     banner="https://example.com/banner.png",
        ...     icon="https://example.com/icon.png",
        ...     pubkey="abcdef1234567890",
        ...     contact=""
        ...     supported_nips=[1, 2, 3],
        ...     software="nostr-relay-software",
        ...     version="1.0.0",
        ...     privacy_policy="https://example.com/privacy",
        ...     terms_of_service="https://example.com/terms",
        ...     limitation={"max_connections": 100},
        ...     extra_fields={"custom_field": "value"}
        ... )

        Returns:
        - None

        Raises:
        - TypeError: if relay is not a Relay
        - TypeError: if generated_at is not an int
        - TypeError: if connection_success is not a bool
        - TypeError: if nip11_success is not a bool
        - TypeError: if openable is not a bool or None
        - TypeError: if readable is not a bool or None
        - TypeError: if writable is not a bool or None
        - TypeError: if rtt_open is not an int or None
        - TypeError: if rtt_read is not an int or None
        - TypeError: if rtt_write is not an int or None
        - TypeError: if name is not a str or None
        - TypeError: if description is not a str or None
        - TypeError: if banner is not a str or None
        - TypeError: if icon is not a str or None
        - TypeError: if pubkey is not a str or None
        - TypeError: if contact is not a str or None
        - TypeError: if supported_nips is not a list of int or None
        - TypeError: if software is not a str or None
        - TypeError: if version is not a str or None
        - TypeError: if privacy_policy is not a str or None
        - TypeError: if terms_of_service is not a str or None
        - TypeError: if limitation is not a dict or None
        - TypeError: if extra_fields is not a dict or None
        - TypeError: if limitation keys are not strings
        - TypeError: if extra_fields keys are not strings
        """
        if not isinstance(relay, Relay):
            raise TypeError(f"relay must be a Relay, not {type(relay)}")
        if not isinstance(generated_at, int):
            raise TypeError(
                f"generated_at must be an int, not {type(generated_at)}")
        if generated_at < 0:
            raise ValueError(
                f"generated_at must be a positive integer, not {generated_at}")
        if not isinstance(connection_success, bool):
            raise TypeError(
                f"connection_success must be a bool, not {type(connection_success)}")
        if not isinstance(nip11_success, bool):
            raise TypeError(
                f"nip11_success must be a bool, not {type(nip11_success)}")
        if openable is not None and not isinstance(openable, bool):
            raise TypeError(
                f"openable must be a boolean or None, not {type(openable)}")
        if readable is not None and not isinstance(readable, bool):
            raise TypeError(
                f"readable must be a boolean or None, not {type(readable)}")
        if writable is not None and not isinstance(writable, bool):
            raise TypeError(
                f"writable must be a boolean or None, not {type(writable)}")
        if rtt_open is not None and not isinstance(rtt_open, int):
            raise TypeError(
                f"rtt_open must be an int or None, not {type(rtt_open)}")
        if rtt_read is not None and not isinstance(rtt_read, int):
            raise TypeError(
                f"rtt_read must be an int or None, not {type(rtt_read)}")
        if rtt_write is not None and not isinstance(rtt_write, int):
            raise TypeError(
                f"rtt_write must be an int or None, not {type(rtt_write)}")
        if name is not None and not isinstance(name, str):
            raise TypeError(f"name must be a string or None, not {type(name)}")
        if description is not None and not isinstance(description, str):
            raise TypeError(
                f"description must be a string or None, not {type(description)}")
        if banner is not None and not isinstance(banner, str):
            raise TypeError(
                f"banner must be a string or None, not {type(banner)}")
        if icon is not None and not isinstance(icon, str):
            raise TypeError(f"icon must be a string or None, not {type(icon)}")
        if pubkey is not None and not isinstance(pubkey, str):
            raise TypeError(
                f"pubkey must be a string or None, not {type(pubkey)}")
        if contact is not None and not isinstance(contact, str):
            raise TypeError(
                f"contact must be a string or None, not {type(contact)}")
        if supported_nips is not None and not isinstance(supported_nips, list):
            raise TypeError(
                f"supported_nips must be a list or None, not {type(supported_nips)}")
        if software is not None and not isinstance(software, str):
            raise TypeError(
                f"software must be a string or None, not {type(software)}")
        if version is not None and not isinstance(version, str):
            raise TypeError(
                f"version must be a string or None, not {type(version)}")
        if privacy_policy is not None and not isinstance(privacy_policy, str):
            raise TypeError(
                f"privacy_policy must be a string or None, not {type(privacy_policy)}")
        if terms_of_service is not None and not isinstance(terms_of_service, str):
            raise TypeError(
                f"terms_of_service must be a string or None, not {type(terms_of_service)}")
        if limitation is not None and not isinstance(limitation, dict):
            raise TypeError(
                f"limitation must be a dictionary or None, not {type(limitation)}")
        if extra_fields is not None and not isinstance(extra_fields, dict):
            raise TypeError(
                f"extra_fields must be a dictionary or None, not {type(extra_fields)}")
        if supported_nips is not None:
            for nip in supported_nips:
                if not (isinstance(nip, int) or isinstance(nip, str)):
                    raise TypeError(
                        f"supported_nips must be a list of integers or strings, not {type(nip)}")
        if limitation is not None:
            for key, value in limitation.items():
                if not isinstance(key, str):
                    raise TypeError(
                        f"limitation keys must be strings, not {type(key)}")
                try:
                    json.dumps(value)
                except (TypeError, ValueError):
                    raise TypeError(
                        f"limitation values must be JSON serializable.")
        if extra_fields is not None:
            for key, value in extra_fields.items():
                if not isinstance(key, str):
                    raise TypeError(
                        f"extra_fields keys must be strings, not {type(key)}")
                try:
                    json.dumps(value)
                except (TypeError, ValueError):
                    raise TypeError(
                        f"extra_fields values must be JSON serializable.")
        self.relay = relay
        self.generated_at = generated_at
        self.connection_success = connection_success
        self.nip11_success = nip11_success
        self.openable = openable if connection_success else None
        self.readable = readable if connection_success else None
        self.writable = writable if connection_success else None
        self.rtt_open = rtt_open if connection_success else None
        self.rtt_read = rtt_read if connection_success else None
        self.rtt_write = rtt_write if connection_success else None
        self.name = name if nip11_success else None
        self.description = description if nip11_success else None
        self.banner = banner if nip11_success else None
        self.icon = icon if nip11_success else None
        self.pubkey = pubkey if nip11_success else None
        self.contact = contact if nip11_success else None
        self.supported_nips = supported_nips if nip11_success else None
        self.software = software if nip11_success else None
        self.version = version if nip11_success else None
        self.privacy_policy = privacy_policy if nip11_success else None
        self.terms_of_service = terms_of_service if nip11_success else None
        self.limitation = limitation if connection_success else None
        self.extra_fields = extra_fields if connection_success else None

    def __repr__(self) -> str:
        """
        Return a string representation of the RelayMetadata object.

        Example:
        >>> relay_metadata = RelayMetadata(
        ...     relay=Relay("wss://relay.example.com"),
        ...     generated_at=1612137600,
        ...     connection_success=False,
        ...     nip11_success=False
        ... )
        >>> print(relay_metadata)
        RelayMetadata(relay=Relay(url=wss://relay.example.com, network=clearnet), generated_at=1612137600, connection_success=False, nip11_success=False)

        Returns:
        - str, string representation of the RelayMetadata object

        Raises:
        - None
        """
        l = []
        for key, value in self.__dict__.items():
            if value is not None:
                l.append(f"{key}={value}")
        return f"RelayMetadata({', '.join(l)})"

    @staticmethod
    def from_dict(data: dict) -> "RelayMetadata":
        """
        Creates a RelayMetadata object from a dictionary.

        Parameters:
        - data: dict, dictionary representation of the RelayMetadata object
        Example:
        >>> data = {
        ...     "relay": Relay("wss://relay.example.com"),
        ...     "generated_at": 1612137600,
        ...     "connection_success": False,
        ...     "nip11_success": False
        ... }
        >>> relay_metadata = RelayMetadata.from_dict(data)
        RelayMetadata(relay=Relay(url=wss://relay.example.com, network=clearnet), generated_at=1612137600, connection_success=False, nip11_success=False)

        Returns:
        - RelayMetadata, RelayMetadata object created from the dictionary

        Raises:
        - TypeError: if data is not a dict
        - KeyError: if data does not contain the required keys
        """
        if not isinstance(data, dict):
            raise TypeError(f"data must be a dict, not {type(data)}")
        required_keys = ["relay", "generated_at",
                         "connection_success", "nip11_success"]
        for key in required_keys:
            if key not in data:
                raise KeyError(f"data must contain key {key}")
        return RelayMetadata(
            relay=data["relay"],
            generated_at=data["generated_at"],
            connection_success=data["connection_success"],
            nip11_success=data["nip11_success"],
            openable=data.get("openable"),
            readable=data.get("readable"),
            writable=data.get("writable"),
            rtt_open=data.get("rtt_open"),
            rtt_read=data.get("rtt_read"),
            rtt_write=data.get("rtt_write"),
            name=data.get("name"),
            description=data.get("description"),
            banner=data.get("banner"),
            icon=data.get("icon"),
            pubkey=data.get("pubkey"),
            contact=data.get("contact"),
            supported_nips=data.get("supported_nips"),
            software=data.get("software"),
            version=data.get("version"),
            privacy_policy=data.get("privacy_policy"),
            terms_of_service=data.get("terms_of_service"),
            limitation=data.get("limitation"),
            extra_fields=data.get("extra_fields"),
        )

    def to_dict(self) -> dict:
        """
        Return a dictionary representation of the RelayMetadata object.

        Example:
        >>> relay_metadata = RelayMetadata(
        ...     relay=Relay("wss://relay.example.com"),
        ...     generated_at=1612137600,
        ...     connection_success=False,
        ...     nip11_success=False
        ... )
        >>> print(relay_metadata.to_dict())
        {'relay': Relay(url=wss://relay.example.com, network=clearnet), 'generated_at': 1612137600, 'connection_success': False, 'nip11_success': False}

        Returns:
        - dict, dictionary representation of the RelayMetadata object

        Raises:
        - None
        """
        return {
            "relay": self.relay,
            "generated_at": self.generated_at,
            "connection_success": self.connection_success,
            "nip11_success": self.nip11_success,
            "openable": self.openable,
            "readable": self.readable,
            "writable": self.writable,
            "rtt_open": self.rtt_open,
            "rtt_read": self.rtt_read,
            "rtt_write": self.rtt_write,
            "name": self.name,
            "description": self.description,
            "banner": self.banner,
            "icon": self.icon,
            "pubkey": self.pubkey,
            "contact": self.contact,
            "supported_nips": self.supported_nips,
            "software": self.software,
            "version": self.version,
            "privacy_policy": self.privacy_policy,
            "terms_of_service": self.terms_of_service,
            "limitation": self.limitation,
            "extra_fields": self.extra_fields,
        }
