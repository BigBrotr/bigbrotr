import psycopg2
from typing import Tuple, Optional
from event import Event
from relay import Relay
from relay_metadata import RelayMetadata
from utils import sanitize


class Bigbrotr:
    """
    Class to connect to the Bigbrotr database.

    Attributes:
    - host: str, the host of the database
    - port: int, the port of the database
    - user: str, the user of the database
    - password: str, the password of the database
    - dbname: str, the name of the database
    - conn: psycopg2.connection, the connection to the database
    - cur: psycopg2.cursor, the cursor of the database

    Methods:
    - connect: connect to the database
    - close: close the connection to the database
    - commit: commit the transaction
    - execute: execute a query
    - fetchall: fetch all the results of the query
    - fetchone: fetch one result of the query
    - fetchmany: fetch many results of the query

    Example:
    >>> host = "localhost"
    >>> port = 5432
    >>> user = "admin"
    >>> password = "admin"
    >>> dbname = "bigbrotr"
    >>> bigbrotr = Bigbrotr(host, port, user, password, dbname)
    >>> bigbrotr.connect()
    >>> query = "SELECT * FROM events"
    >>> bigbrotr.execute(query)
    >>> results = bigbrotr.fetchall()
    >>> for row in results:
    >>>     print(row)
    >>> bigbrotr.close()
    """

    def __init__(self, host: str, port: int, user: str, password: str, dbname: str):
        """
        Initialize a Bigbrotr object.

        Parameters:
        - host: str, the host of the database
        - port: int, the port of the database
        - user: str, the user of the database
        - password: str, the password of the database
        - dbname: str, the name of the database

        Example:
        >>> host = "localhost"
        >>> port = 5432
        >>> user = "admin"
        >>> password = "admin"
        >>> dbname = "bigbrotr"
        >>> bigbrotr = Bigbrotr(host, port, user, password, dbname)

        Returns:
        - Bigbrotr, a Bigbrotr object

        Raises:
        - TypeError: if host is not a str
        - TypeError: if port is not an int
        - TypeError: if user is not a str
        - TypeError: if password is not a str
        - TypeError: if dbname is not a str
        """
        if not isinstance(host, str):
            raise TypeError(f"host must be a str, not {type(host)}")
        if not isinstance(port, int):
            raise TypeError(f"port must be an int, not {type(port)}")
        if not isinstance(user, str):
            raise TypeError(f"user must be a str, not {type(user)}")
        if not isinstance(password, str):
            raise TypeError(f"password must be a str, not {type(password)}")
        if not isinstance(dbname, str):
            raise TypeError(f"dbname must be a str, not {type(dbname)}")
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.dbname = dbname
        self.conn = None
        self.cur = None
        return

    def connect(self):
        """
        Connect to the database.

        Example:
        >>> bigbrotr.connect()

        Returns:
        - None

        Raises:
        - None
        """
        self.conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.dbname
        )
        self.cur = self.conn.cursor()
        return

    def close(self):
        """
        Close the connection to the database.

        Example:
        >>> bigbrotr.close()

        Returns:
        - None

        Raises:
        - None
        """
        self.cur.close()
        self.conn.close()
        return

    def commit(self):
        """
        Commit the transaction.

        Example:
        >>> bigbrotr.commit()

        Returns:
        - None

        Raises:
        - None
        """
        self.conn.commit()
        return

    def execute(self, query: str, args: Optional[Tuple] = ()):
        """
        Execute a query.

        Parameters:
        - query: str, the query to execute
        - args: Optional[Tuple], the arguments to pass to the query

        Example:
        >>> query = "SELECT * FROM events"
        >>> bigbrotr.execute(query)

        Returns:
        - None

        Raises:
        - TypeError: if query is not a str
        - TypeError: if args is not a tuple
        """
        if not isinstance(query, str):
            raise TypeError(f"query must be a str, not {type(query)}")
        if not isinstance(args, tuple):
            raise TypeError(f"args must be a tuple, not {type(args)}")
        self.cur.execute(query, args)
        return

    def fetchall(self):
        """
        Fetch all the results of the query.

        Example:
        >>> bigbrotr.fetchall()

        Returns:
        - List[Tuple], a list of tuples

        Raises:
        - None
        """
        return self.cur.fetchall()

    def fetchone(self):
        """
        Fetch one result of the query.

        Example:
        >>> bigbrotr.fetchone()

        Returns:
        - Tuple, a tuple

        Raises:
        - None
        """
        return self.cur.fetchone()

    def fetchmany(self, size: int):
        """
        Fetch many results of the query.

        Parameters:
        - size: int, the number of results to fetch

        Example:
        >>> size = 5
        >>> bigbrotr.fetchmany(size)

        Returns:
        - List[Tuple], a list of tuples

        Raises:
        - TypeError: if size is not an int
        """
        if not isinstance(size, int):
            raise TypeError(f"size must be an int, not {type(size)}")
        return self.cur.fetchmany(size)

    def delete_orphan_events(self):
        """
        Delete orphan events from the database.

        Parameters:
        - None

        Example:
        >>> bigbrotr.delete_orphan_events()

        Returns:
        - None

        Raises:
        - None
        """
        query = "SELECT delete_orphan_events()"
        self.execute(query)
        self.commit()
        return

    def insert_event(self, event: Event, relay: Relay, seen_at: int) -> None:
        """
        Insert an event into the database.

        Parameters:
        - event: Event, the event to insert
        - relay: Relay, the relay to insert
        - seen_at: int, the time the event was seen

        Example:
        >>> event = Event(...)
        >>> relay = Relay(...)
        >>> seen_at = 1234567890
        >>> bigbrotr.insert_event(event, relay, seen_at)

        Returns:
        - None

        Raises:
        - TypeError: if event is not an Event
        - TypeError: if relay is not a Relay
        - TypeError: if seen_at is not an int
        """
        if not isinstance(event, Event):
            raise TypeError(f"event must be an Event, not {type(event)}")
        if not isinstance(relay, Relay):
            raise TypeError(f"relay must be a Relay, not {type(relay)}")
        if not isinstance(seen_at, int):
            raise TypeError(f"seen_at must be an int, not {type(seen_at)}")
        query = "SELECT insert_event(%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)"
        args = (
            event.id,
            event.pubkey,
            event.created_at,
            event.kind,
            sanitize(event.tags),
            sanitize(event.content),
            event.sig,
            sanitize(relay.url),
            relay.network,
            seen_at
        )
        self.execute(query, args)
        self.commit()
        return

    def insert_relay(self, relay: Relay) -> None:
        """
        Insert a relay into the database.

        Parameters:
        - relay: Relay, the relay to insert

        Example:
        >>> relay = Relay(url="wss://relay.nostr.com")
        >>> bigbrotr.insert_relay(relay)

        Returns:
        - None

        Raises:
        - TypeError: if relay is not a Relay
        """
        if not isinstance(relay, Relay):
            raise TypeError(f"relay must be a Relay, not {type(relay)}")
        query = "SELECT insert_relay(%s, %s)"
        args = (
            sanitize(relay.url),
            relay.network
        )
        self.execute(query, args)
        self.commit()
        return

    def insert_relay_metadata(self, relay_metadata: RelayMetadata) -> None:
        """
        Insert a relay metadata into the database.

        Parameters:
        - relay_metadata: RelayMetadata, the relay metadata to insert

        Example:
        >>> relay_metadata = RelayMetadata(...)
        >>> bigbrotr.insert_relay_metadata(relay_metadata)

        Returns:
        - None

        Raises:
        - TypeError: if relay_metadata is not a RelayMetadata
        """
        if not isinstance(relay_metadata, RelayMetadata):
            raise TypeError(
                f"relay_metadata must be a RelayMetadata, not {type(relay_metadata)}")
        query = "SELECT insert_relay_metadata(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s::jsonb)"
        args = (
            sanitize(relay_metadata.relay.url),
            relay_metadata.relay.network,
            relay_metadata.generated_at,
            relay_metadata.connection_success,
            relay_metadata.nip11_success,
            relay_metadata.readable,
            relay_metadata.writable,
            relay_metadata.rtt,
            sanitize(relay_metadata.name),
            sanitize(relay_metadata.description),
            sanitize(relay_metadata.banner),
            sanitize(relay_metadata.icon),
            sanitize(relay_metadata.pubkey),
            sanitize(relay_metadata.contact),
            sanitize(relay_metadata.supported_nips),
            sanitize(relay_metadata.software),
            sanitize(relay_metadata.version),
            sanitize(relay_metadata.privacy_policy),
            sanitize(relay_metadata.terms_of_service),
            sanitize(relay_metadata.limitations),
            sanitize(relay_metadata.extra_fields)
        )
        self.execute(query, args)
        self.commit()
        return

    def insert_event_batch(self, events: list[Event], relay: Relay, seen_at: int) -> None:
        """
        Insert a batch of events into the database.

        Parameters:
        - events: list[Event], the events to insert
        - relay: Relay, the relay to insert
        - seen_at: int, the time the event was seen

        Example:
        >>> events = [Event(...), Event(...)]
        >>> relay = Relay(...)
        >>> seen_at = 1234567890
        >>> bigbrotr.insert_event_batch(events, relay, seen_at)

        Returns:
        - None

        Raises:
        - TypeError: if events is not a list of Event
        - TypeError: if relay is not a Relay
        - TypeError: if seen_at is not an int
        """
        if not isinstance(events, list):
            raise TypeError(f"events must be a list, not {type(events)}")
        for event in events:
            if not isinstance(event, Event):
                raise TypeError(
                    f"event must be an Event, not {type(event)}")
        if not isinstance(relay, Relay):
            raise TypeError(f"relay must be a Relay, not {type(relay)}")
        if not isinstance(seen_at, int):
            raise TypeError(f"seen_at must be an int, not {type(seen_at)}")
        query = "SELECT insert_event(%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)"
        args = [
            (
                event.id,
                event.pubkey,
                event.created_at,
                event.kind,
                sanitize(event.tags),
                sanitize(event.content),
                event.sig,
                sanitize(relay.url),
                relay.network,
                seen_at
            )
            for event in events
        ]
        self.cur.executemany(query, args)
        self.commit()
        return

    def insert_relay_batch(self, relays: list[Relay]) -> None:
        """
        Insert a batch of relays into the database.

        Parameters:
        - relays: list[Relay], the relays to insert

        Example:
        >>> relays = [Relay(url="wss://relay1.com"), Relay(url="wss://relay2.com")]
        >>> bigbrotr.insert_relay_batch(relays)

        Returns:
        - None

        Raises:
        - TypeError: if relays is not a list of Relay
        """
        if not isinstance(relays, list):
            raise TypeError(f"relays must be a list, not {type(relays)}")
        for relay in relays:
            if not isinstance(relay, Relay):
                raise TypeError(
                    f"relay must be a Relay, not {type(relay)}")
        query = "SELECT insert_relay(%s, %s)"
        args = [
            (
                sanitize(relay.url),
                relay.network
            )
            for relay in relays
        ]
        self.cur.executemany(query, args)
        self.commit()
        return

    def insert_relay_metadata_batch(self, relay_metadata_list: list[RelayMetadata]) -> None:
        """
        Insert a batch of relay metadata into the database.

        Parameters:
        - relay_metadata_list: list[RelayMetadata], the relay metadata to insert

        Example:
        >>> relay_metadata_list = [RelayMetadata(...), RelayMetadata(...)]
        >>> bigbrotr.insert_relay_metadata_batch(relay_metadata_list)

        Returns:
        - None

        Raises:
        - TypeError: if relay_metadata_list is not a list of RelayMetadata
        """
        if not isinstance(relay_metadata_list, list):
            raise TypeError(
                f"relay_metadata_list must be a list, not {type(relay_metadata_list)}")
        for relay_metadata in relay_metadata_list:
            if not isinstance(relay_metadata, RelayMetadata):
                raise TypeError(
                    f"relay_metadata must be a RelayMetadata, not {type(relay_metadata)}")
        query = "SELECT insert_relay_metadata(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s::jsonb)"
        args = [
            (
                sanitize(relay_metadata.relay.url),
                relay_metadata.relay.network,
                relay_metadata.generated_at,
                relay_metadata.connection_success,
                relay_metadata.nip11_success,
                relay_metadata.readable,
                relay_metadata.writable,
                relay_metadata.rtt,
                sanitize(relay_metadata.name),
                sanitize(relay_metadata.description),
                sanitize(relay_metadata.banner),
                sanitize(relay_metadata.icon),
                sanitize(relay_metadata.pubkey),
                sanitize(relay_metadata.contact),
                sanitize(relay_metadata.supported_nips),
                sanitize(relay_metadata.software),
                sanitize(relay_metadata.version),
                sanitize(relay_metadata.privacy_policy),
                sanitize(relay_metadata.terms_of_service),
                sanitize(relay_metadata.limitations),
                sanitize(relay_metadata.extra_fields)
            )
            for relay_metadata in relay_metadata_list
        ]
        self.cur.executemany(query, args)
        self.commit()
        return
