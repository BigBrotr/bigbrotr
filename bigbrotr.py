import psycopg2


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

    def __init__(self, host: str, port: int, user: str, password: str, dbname: str) -> "Bigbrotr":
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

    def execute(self, query: str, args: tuple = ()):
        """
        Execute a query.

        Parameters:
        - query: str, the query to execute
        - args: tuple, the arguments of the query

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
