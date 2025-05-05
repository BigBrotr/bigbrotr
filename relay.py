import re


class Relay:
    """
    Class to represent a NOSTR relay.

    Attributes:
    - url: str, url of the relay
    - network: str, network of the relay

    Methods:
    - __init__(url: str) -> None: initialize the Relay object
    - __repr__() -> str: return the string representation of the Relay object
    - from_dict(data: dict) -> Relay: create a Relay object from a dictionary
    - to_dict() -> dict: return the Relay object as a dictionary
    """

    def __init__(self, url: str) -> None:
        """
        Initialize a Relay object.

        Parameters:
        - url: str, url of the relay

        Example:
        >>> url = "wss://relay.nostr.com"
        >>> relay = Relay(url)

        Returns:
        - None

        Raises:
        - TypeError: if url is not a str
        - ValueError: if url does not start with 'wss://' or 'ws://'
        """
        if not isinstance(url, str):
            raise TypeError(f"url must be a str, not {type(url)}")
        if not url.startswith("wss://") and not url.startswith("ws://"):
            raise ValueError(
                f"url must start with 'wss://' or 'ws://', not {url}")
        self.url = url
        if re.match(r"^(wss://|ws://)?[abcdefghjkmnpqrstuvwxyz234567]{16,56}\.onion(?::(6553[0-5]|655[0-2]\d|65[0-4]\d{2}|6[0-4]\d{3}|[1-5]?\d{1,4}))?/?$", url):
            self.network = "tor"
        else:
            self.network = "clearnet"

    def __repr__(self) -> str:
        """
        Return the string representation of the Relay object.

        Parameters:
        - None

        Example:
        >>> url = "wss://relay.nostr.com"
        >>> relay = Relay(url)
        >>> relay
        Relay(url=wss://relay.nostr.com, network=clearnet)

        Returns:
        - str, string representation of the Relay object

        Raises:
        - None
        """
        return f"Relay(url={self.url}, network={self.network})"

    @staticmethod
    def from_dict(data: dict) -> "Relay":
        """
        Create a Relay object from a dictionary.

        Parameters:
        - data: dict, dictionary to create the Relay object from

        Example:
        >> > data = {"url": "wss://relay.nostr.com"}
        >> > relay = Relay.from_dict(data)
        >> > relay
        Relay(url=wss://relay.nostr.com, network=clearnet)

        Returns:
        - Relay, a Relay object

        Raises:
        - TypeError: if data is not a dict
        - KeyError: if data does not contain key 'url'
        """
        if not isinstance(data, dict):
            raise TypeError(f"data must be a dict, not {type(data)}")
        if "url" not in data:
            raise KeyError(f"data must contain key {'url'}")
        return Relay(data["url"])

    def to_dict(self) -> dict:
        """
        Return the Relay object as a dictionary.

        Parameters:
        - None

        Example:
        >> > url = "wss://relay.nostr.com"
        >> > relay = Relay(url)
        >> > relay.to_dict()
        {"url": "wss://relay.nostr.com", "network": "clearnet"}

        Returns:
        - dict, dictionary representation of the Relay object

        Raises:
        - None
        """
        return {"url": self.url, "network": self.network}
