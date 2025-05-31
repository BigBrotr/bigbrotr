from typing import List
from utils import calc_event_id, verify_sig
import json


class Event:
    """
    Class to represent a NOSTR event.

    Attributes:
    - id: str, id of the event
    - pubkey: str, public key of the event
    - created_at: int, timestamp of the event
    - kind: int, kind of the event
    - tags: List[List[str]], tags of the event
    - content: str, content of the event
    - sig: str, signature of the event

    Methods:
    - __init__(id: str, pubkey: str, created_at: int, kind: int, tags: List[List[str]], content: str, sig: str) -> None: initialize the Event object
    - __repr__() -> str: return the string representation of the Event object
    - from_dict(data: dict) -> Event: create an Event object from a dictionary
    - to_dict() -> dict: return the Event object as a dictionary
    """

    def __init__(self, id: str, pubkey: str, created_at: int, kind: int, tags: List[List[str]], content: str, sig: str) -> "Event":
        """
        Initialize an Event object.

        Parameters:
        - id: str, id of the event
        - pubkey: str, public key of the event
        - created_at: int, timestamp of the event
        - kind: int, kind of the event
        - tags: List[List[str]], tags of the event
        - content: str, content of the event
        - sig: str, signature of the event

        Example:
        >>> id = "0x123"
        >>> pubkey = "0x123"
        >>> created_at = 1612137600
        >>> kind = 0
        >>> tags = [["tag1", "tag2"]]
        >>> content = "content"
        >>> sig = "0x123"
        >>> event = Event(id, pubkey, created_at, kind, tags, content, sig)

        Returns:
        - Event, Event object initialized with the provided parameters

        Raises:
        - TypeError: if id is not a str
        - TypeError: if pubkey is not a str
        - TypeError: if created_at is not an int
        - TypeError: if kind is not an int
        - TypeError: if tags is not a list of lists of str
        - TypeError: if content is not a str
        - TypeError: if sig is not a str
        - ValueError: if kind is not between 0 and 65535
        - ValueError: if the event id is invalid
        - ValueError: if the event signature is invalid
        """
        if not isinstance(id, str):
            raise TypeError(f"id must be a str, not {type(id)}")
        if not isinstance(pubkey, str):
            raise TypeError(f"pubkey must be a str, not {type(pubkey)}")
        if not isinstance(created_at, int):
            raise TypeError(
                f"created_at must be an int, not {type(created_at)}")
        if not isinstance(kind, int):
            raise TypeError(f"kind must be an int, not {type(kind)}")
        if not isinstance(tags, list):
            raise TypeError(
                f"tags must be a list of lists of str, not {type(tags)}")
        for tag in tags:
            if not isinstance(tag, list):
                raise TypeError(f"tag must be a list of str, not {type(tag)}")
            for t in tag:
                if not isinstance(t, str):
                    raise TypeError(f"tag must contain str, not {type(t)}")
        if not isinstance(content, str):
            raise TypeError(f"content must be a str, not {type(content)}")
        if not isinstance(sig, str):
            raise TypeError(f"sig must be a str, not {type(sig)}")
        if kind < 0 or kind > 65535:
            raise ValueError(f"kind must be between 0 and 65535, not {kind}")
        if created_at < 0:
            raise ValueError(
                f"created_at must be a positive int, not {created_at}")
        if len(id) != 64:
            raise ValueError(f"id must be 64 characters long, not {len(id)}")
        if len(pubkey) != 64:
            raise ValueError(
                f"pubkey must be 64 characters long, not {len(pubkey)}")
        if len(sig) != 128:
            raise ValueError(
                f"sig must be 128 characters long, not {len(sig)}")
        if "\\u0000" in json.dumps(tags):
            raise ValueError("tags cannot contain null characters")
        if "\\u0000" in json.dumps(content):
            raise ValueError("content cannot contain null characters")
        if calc_event_id(pubkey, created_at, kind, tags, content) != id:
            raise ValueError(f"Invalid event id: {id}")
        if verify_sig(id, pubkey, sig) != True:
            raise ValueError(f"Invalid event signature: {sig}")
        self.id = id
        self.pubkey = pubkey
        self.created_at = created_at
        self.kind = kind
        self.tags = tags
        self.content = content
        self.sig = sig
        return

    def __repr__(self) -> str:
        """
        Return a string representation of the Event object.

        Parameters:
        - None

        Example:
        >>> event = Event(id, pubkey, created_at, kind, tags, content, sig)
        >>> event
        Event(id=0x123, pubkey=0x123, created_at=1612137600, kind=0, tags=[["tag1", "tag2"]], content=content, sig=0x123)

        Returns:
        - str, string representation of the Event object

        Raises:
        - None
        """
        return f"Event(id={self.id}, pubkey={self.pubkey}, created_at={self.created_at}, kind={self.kind}, tags={self.tags}, content={self.content}, sig={self.sig})"

    @staticmethod
    def from_dict(data: dict) -> "Event":
        """
        Create an Event object from a dictionary.

        Parameters:
        - data: dict, dictionary representation of the Event object

        Example:
        >>> data = {"id": "0x123", "pubkey": "0x123", "created_at": 1612137600, "kind": 0, "tags": [["tag1", "tag2"]], "content": "content", "sig": "0x123"}
        >>> event = Event.from_dict(data)
        Event(id=0x123, pubkey=0x123, created_at=1612137600, kind=0, tags=[["tag1", "tag2"]], content=content, sig=0x123)

        Returns:
        - Event, Event object created from the dictionary

        Raises:
        - TypeError: if data is not a dict
        - KeyError: if data does not contain the required keys
        """
        if not isinstance(data, dict):
            raise TypeError(f"data must be a dict, not {type(data)}")
        for key in ["id", "pubkey", "created_at", "kind", "tags", "content", "sig"]:
            if key not in data:
                raise KeyError(f"data must contain key {key}")
        return Event(data["id"], data["pubkey"], data["created_at"], data["kind"], data["tags"], data["content"], data["sig"])

    def to_dict(self) -> dict:
        """
        Return a dictionary representation of the Event object.

        Parameters:
        - None

        Example:
        >>> event = Event(id, pubkey, created_at, kind, tags, content, sig)
        >>> event.to_dict()
        {'id': '0x123', 'pubkey': '0x123', 'created_at': 1612137600, 'kind': 0, 'tags': [['tag1', 'tag2']], 'content': 'content', 'sig': '0x123'}

        Returns:
        - dict, dictionary representation of the Event object

        Raises:
        - None
        """
        return {"id": self.id, "pubkey": self.pubkey, "created_at": self.created_at, "kind": self.kind, "tags": self.tags, "content": self.content, "sig": self.sig}
