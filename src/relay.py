import utils


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
        >>> relay = Relay("wss://relay.nostr.com")

        Returns:
        - None

        Raises:
        - TypeError: if url is not a str
        - ValueError: if url does not start with 'wss://' or 'ws://'
        """
        if not isinstance(url, str):
            raise TypeError(f"url must be a str, not {type(url)}")
        urls = utils.find_websoket_relay_urls(url)
        if urls == []:
            raise ValueError(
                f"Invalid URL format: {url}. Must be a valid clearnet or tor websocket URL.")
        url = urls[0]
        if url.removeprefix("wss://").partition(":")[0].endswith(".onion"):
            self.network = "tor"
        else:
            self.network = "clearnet"
        self.url = url

    def __repr__(self) -> str:
        """
        Return the string representation of the Relay object.

        Parameters:
        - None

        Example:
        >>> relay = Relay("wss://relay.nostr.com")
        >>> relay
        Relay(url=relay.nostr.com, network=clearnet)

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
        >>> data = {"url": "wss://relay.nostr.com"}
        >>> relay = Relay.from_dict(data)
        >>> relay
        Relay(url=relay.nostr.com, network=clearnet)

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
        >>> relay = Relay("wss://relay.nostr.com")
        >>> relay.to_dict()
        {"url": "relay.nostr.com", "network": "clearnet"}

        Returns:
        - dict, dictionary representation of the Relay object

        Raises:
        - None
        """
        return {"url": self.url, "network": self.network}
