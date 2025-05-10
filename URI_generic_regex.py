# https://www.rfc-editor.org/rfc/rfc3986
# URI = scheme ":" hier-part [ "?" query ] [ "#" fragment ]
# scheme      = ALPHA *( ALPHA / DIGIT / "+" / "-" / "." )
# hier-part   = "//" authority path-abempty
#               / path-absolute
#               / path-rootless / path-empty
# authority   = [ userinfo "@" ] host [ ":" port ]
# userinfo    = *( unreserved / pct-encoded / sub-delims / ":" )
# host        = IP-literal / IPv4address / reg-name
# port        = *DIGIT
# path-abempty = *( "/" segment )

# scheme:    https
# hier-part: //user:pass@www.example.com:443/path/to/resource
# authority: user:pass@www.example.com:443
#     userinfo: user:pass
#     host: www.example.com
#     port: 443
# path: /path/to/resource
# query: query=value
# fragment: fragment

URI_GENERIC_REGEX = r'''

    # ==== Scheme ====
    (?P<scheme>[a-zA-Z][a-zA-Z0-9+\-.]*):       # Group 1 for the scheme:
                                               # - Starts with a letter
                                               # - Followed by letters, digits, '+', '-', or '.'
                                               # - Ends with a colon ':'

    \/\/                                       # Double forward slashes '//' separating scheme and authority

    # ==== Optional User Info ====
    (?P<userinfo>                              # Group 2 for optional userinfo group
        [A-Za-z0-9\-\._~!$&'()*+,;=:%]*@       # Userinfo (username[:password]) part, ending with '@'
                                               # - Includes unreserved, sub-delims, ':' and '%'
    )?                                         # Entire userinfo is optional

    # ==== Host (IPv6, IPv4, or Domain) ====
    (?P<host>                                  # Group 3 for host group
        # --- IPv6 Address ---
        \[                                     # Opening square bracket
            (?P<ipv6>([0-9a-fA-F]{1,4}:){7}     # Group 4 for IPv6 address part
                ([0-9a-fA-F]{1,4}))             # Final 1-4 hex digits (total 8 groups)
        \]                                     # Closing square bracket

        |                                      # OR

        # --- IPv4 Address ---
        (?P<ipv4>(\d{1,3}\.){3}                 # Group 5 for IPv4 address part
            \d{1,3})                            # Final group of 1–3 digits (e.g., 192.168.0.1)

        |                                      # OR

        # --- Registered Domain Name ---
        (?P<domain>                             # Group 6 for domain part
            (?:                                 # Non-capturing group for domain labels:
                [a-zA-Z0-9]                     # Label must start with a letter or digit
                (?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])? # Middle part (0–61 chars) ending in letter/digit (no trailing hyphen)
            )+                                    # Repeat for each subdomain
            \.                                  # Dot before TLD
            [a-zA-Z]{2,}                         # TLD must be at least 2 alphabetic characters
        )                                        # End of domain group
        
        # |                                       # OR
        
        # (?P<localhost>localhost)                 # Special case for 'localhost'
    )                                          # End of host group

    # ==== Optional Port ====
    (?P<port>:\d+)?                             # Group 7 for optional port number prefixed by a colon (e.g., :80)

    # ==== Path ====
    (?P<path>                                  # Group 8 for the path group
        /?                                      # Optional leading slash
        (?:                                     # Non-capturing group for path segments
            [a-zA-Z0-9\-_~!$&'()*+,;=:%]+       # Path segments (e.g., '/files', '/images', etc.)
            (?:/[a-zA-Z0-9\-_~!$&'()*+,;=:%]+)* # Optional repeated path segments
            (?:\.[a-zA-Z0-9\-]+)*                # Allow a file extension (e.g., '.txt', '.jpg', '.html')
        )?                                       
    )                                          # End of path group

    # ==== Optional Query ====
    (?P<query>\?                                 # Group 9 for query starts with '?'
        [a-zA-Z0-9\-_~!$&'()*+,;=:%/?]*         # Query parameters (key=value pairs or just data)
    )?                                         # Entire query is optional

    # ==== Optional Fragment ====
    (?P<fragment>\#                             # Group 10 for fragment starts with '#'
        [a-zA-Z0-9\-_~!$&'()*+,;=:%/?]*         # Fragment identifier (can include same characters as query)
    )?                                         # Entire fragment is optional

    '''

# Example usage
if __name__ == "__main__":
    import re
    text = """
        This is a test string with some URIs:
        - https://example.com
        - http://example.org
        - ftp://example.net
        x file:///path/to/file
        - https://www.example.com/path/to/resource?query=string#fragment
        - https://example.com/path/to/resource?query=string#fragment
        - http://example.com/path/to/resource?query=string#fragment
        - https://www.example.com/path/to/file?query=123#fragment
        - ftp://username:password@ftp.example.org:21/path/to/file
        - http://localhost:8080/test
        - https://example.com/path/to/resource?query=string#fragment.
        - http://[1080:0:0:0:8:800:200C:417A]/index.html
        x ssh://user@host:22/path/to/file
        - telnet://example.com:23
        x mailto:example.gmail.com
        - https://example.com/path/to/resource?query=string#fragment,
    """
    matches = re.finditer(URI_GENERIC_REGEX, text, re.VERBOSE)
    for match in matches:
        print(match.group(0))
        print(match.start(), match.end())
        print(match.groupdict())
        print('-' * 20)
        print()