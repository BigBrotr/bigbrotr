class Relay:
    """
    Class to represent a NOSTR relay.

    Attributes:
    - url: str, url of the relay

    Methods:
    - __init__(url: str) -> None: initialize the Relay object
    - __repr__() -> str: return the string representation of the Relay object
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
        """
        if not isinstance(url, str):
            raise TypeError(f"url must be a str, not {type(url)}")
        if not url.startswith("wss://") and not url.startswith("ws://"):
            raise ValueError(f"url must start with 'wss://' or 'ws://', not {url}")
        self.url = url
        return
    
    def __repr__(self) -> str:
        """
        Return the string representation of the Relay object.

        Returns:
        - str, string representation of the Relay object
        """
        return f"Relay(url={self.url})"