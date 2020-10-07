import asyncio
import http.client
import ipaddress
import json
import os
import re
import ssl
import typing
import urllib.parse

from ._config import (
    allowed_schemes,
    cafile,
    capath,
    headers,
    local_domains,
    paths_data,
    paths_redirects,
    redirect_codes,
    replacements,
    ssl_ciphers,
    ssl_options,
    ssl_verify_flags,
    timeout
)
from ._exceptions import InvalidURL, InvalidScheme, InvalidList
from ._regex import mime

loop = asyncio.get_event_loop()

# https://github.com/psf/requests/blob/v2.24.0/requests/utils.py#L566
UNRESERVED_SET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" + "0123456789-._~")

# https://github.com/psf/requests/blob/v2.24.0/requests/utils.py#L570
async def unquote_unreserved(uri: str) -> str:
    """Un-escape any percent-escape sequences in a URI that are unreserved
    characters. This leaves all reserved, illegal and non-ASCII bytes encoded.
    """
    parts = uri.split("%")
    for i in range(1, len(parts)):
        h = parts[i][0:2]
        if len(h) == 2 and h.isalnum():
            c = chr(int(h, 16))
            if c in UNRESERVED_SET:
                parts[i] = c + parts[i][2:]
            else:
                parts[i] = "%" + parts[i]
        else:
            parts[i] = "%" + parts[i]
    return "".join(parts)

# https://github.com/psf/requests/blob/v2.24.0/requests/utils.py#L594
async def requote_uri(uri: str) -> str:
    """Re-quote the given URI.

    This function passes the given URI through an unquote/quote cycle to
    ensure that it is fully and consistently quoted.
    """
    safe_with_percent = "!#$%&'()*+,/:;=?@[]~"
    safe_without_percent = "!#$&'()*+,/:;=?@[]~"
    try:
        # Unquote only the unreserved characters
        # Then quote only illegal characters (do not quote reserved,
        # unreserved, or '%')
        return urllib.parse.quote(await unquote_unreserved(uri), safe=safe_with_percent)
    except ValueError:
        # We couldn't unquote the given URI, so let"s try quoting it, but
        # there may be unquoted "%"s in the URI. We need to make sure they're
        # properly quoted so they do not cause issues elsewhere.
        return urllib.parse.quote(uri, safe=safe_without_percent)

# https://github.com/psf/requests/blob/v2.24.0/requests/utils.py#L894
async def prepend_scheme_if_needed(url: str, new_scheme: str) -> str:
    """Given a URL that may or may not have a scheme, prepend the given scheme.
    Does not replace a present scheme with the one provided as an argument.
    """
    scheme, netloc, path, params, query, fragment = urllib.parse.urlparse(url, new_scheme)

    # urlparse is a finicky beast, and sometimes decides that there isn't a
    # netloc present. Assume that it's being over-cautious, and switch netloc
    # and path if urlparse decided there was no netloc.
    if not netloc:
        netloc, path = path, netloc

    return urllib.parse.urlunparse((scheme, netloc, path, params, query, fragment))

# https://github.com/psf/requests/blob/v2.24.0/requests/utils.py#L953
async def urldefragauth(url: str) -> str:
    """Given a url remove the fragment and the authentication part."""
    scheme, netloc, path, params, query, fragment = urllib.parse.urlparse(url)

    # see func:`prepend_scheme_if_needed`
    if not netloc:
        netloc, path = path, netloc

    netloc = netloc.rsplit("@", 1)[-1]

    return urllib.parse.urlunparse((scheme, netloc, path, params, query, ''))

async def is_private(url: str) -> bool:
    """This function checks if the URL's netloc belongs to a local/private network.

    Usage:
      >>> from unalix._utils import is_private
      >>> is_private("http://0.0.0.0/")
      True
    """
    netloc = urllib.parse.urlparse(url).netloc
    
    try:
        address = ipaddress.ip_address(netloc)
    except ValueError:
        return (netloc in local_domains)
    else:
        return address.is_private

# This function is based on:
# https://github.com/encode/httpx/blob/0.16.1/httpx/_config.py#L98
# https://github.com/encode/httpx/blob/0.16.1/httpx/_config.py#L151
async def creat_ssl_context() -> ssl.SSLContext:
    """This function creats the default SSL context for HTTPS connections.

    Usage:
      >>> from unalix._utils import creat_ssl_context
      >>> creat_ssl_context()
      <ssl.SSLContext object at 0xad6a9070>
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.options = ssl_options
    context.verify_flags = ssl_verify_flags
    context.set_ciphers(ssl_ciphers)

    if ssl.HAS_ALPN:
        context.set_alpn_protocols(["http/1.1"])

    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.load_verify_locations(cafile=cafile, capath=capath)

    # Signal to server support for PHA in TLS 1.3. Raises an
    # AttributeError if only read-only access is implemented.
    try:
        context.post_handshake_auth = True
    except AttributeError:
        pass

    # Disable using 'commonName' for SSLContext.check_hostname
    # when the 'subjectAltName' extension isn't available.
    try:
        context.hostname_checks_common_name = False
    except AttributeError:
        pass

    return context

async def creat_connection(scheme: str, netloc: str) -> typing.Union[http.client.HTTPConnection, http.client.HTTPSConnection]: # type: ignore
    """This function is used to creat HTTP and HTTPS connections.
    
    Parameters:
        scheme (``str``):
            Scheme (must be 'http' or 'https').

        netloc (``str``):
            Netloc or hostname.

    Raises:
        InvalidScheme: In case the provided *scheme* is not valid.

    Usage:
      >>> from unalix._utils import creat_connection
      >>> creat_connection("http", "example.com")
      <http.client.HTTPConnection object at 0xad219bb0>
    """
    if scheme == "http":
        connection = http.client.HTTPConnection(netloc, timeout=timeout)
    elif scheme == "https":
        connection = http.client.HTTPSConnection(netloc, context=context, timeout=timeout)
    else:
        raise InvalidScheme(f"Expecting 'http' or 'https', but got: {scheme}")
        
    return connection

async def parse_url(url: str) -> str:
    """Parse and format the given URL.

    This function has three purposes:

    - Add the "http://" prefix if the *url* provided does not have a defined scheme.
    - Convert domain names in non-Latin alphabet to punycode.
    - Remove the fragment and the authentication part (e.g 'user:pass@') from the URL.

    Parameters:
        url (``str``):
            Full URL or hostname.

    Raises:
        InvalidURL: In case the provided *url* is not a valid URL or hostname.

        InvalidScheme: In case the provided *url* has a invalid or unknown scheme.

    Usage:
      >>> from unalix._utils import parse_url
      >>> parse_url("i❤️.ws")
      'http://xn--i-7iq.ws/'
    """
    if not isinstance(url, str) or not url:
        raise InvalidURL("This is not a valid URL")

    # If the specified URL does not have a scheme defined, it will be set to 'http'.
    url = await prepend_scheme_if_needed(url, "http")

    # Remove the fragment and the authentication part (e.g 'user:pass@') from the URL.
    url = await urldefragauth(url)

    scheme, netloc, path, params, query, fragment = urllib.parse.urlparse(url)
    
    # We don't want to process URLs with protocols other than those
    if not scheme in allowed_schemes:
        raise InvalidScheme(f"Expecting 'http' or 'https', but got: {scheme}")

    # Encode domain name according to IDNA.
    netloc = netloc.encode("idna").decode('utf-8')

    url = urllib.parse.urlunparse((scheme, netloc, path, params, query, fragment))

    return url

async def clear_url(url: str, **kwargs) -> str:
    """Remove tracking fields from the given URL.

    Parameters:
        url (``str``):
            Some URL with tracking fields.

        **kwargs (``bool``, *optional*):
            Optional arguments that `parse_rules` takes.

    Raises:
        InvalidURL: In case the provided *url* is not a valid URL or hostname.

        InvalidScheme: In case the provided *url* has a invalid or unknown scheme.

    Usage:
      >>> from unalix import clear_url
      >>> clear_url("https://deezer.com/track/891177062?utm_source=deezer")
      'https://deezer.com/track/891177062'
    """
    formated_url = await parse_url(url)
    cleaned_url = await parse_rules(formated_url, **kwargs)

    return cleaned_url

async def extract_url(response: http.client.HTTPResponse, url: str, **kwargs) -> typing.Union[str, None]:
    """This function is used to extract redirect links from HTML pages."""
    for redirect_rule in redirects:
        if redirect_rule["pattern"].match(url):
            if not response.isclosed():
                content = response.read()
                response.close()
                document = content.decode()
            for redirect in redirect_rule["redirects"]:
                result = redirect.match(document) # type: ignore
                try:
                    extracted_url = result.group(1)
                except AttributeError:
                    continue
                else:
                    return await parse_rules(extracted_url, **kwargs)

    return None

async def unshort_url(url: str, parse_documents: bool = False, **kwargs) -> str:
    """Try to unshort the given URL (follow http redirects).

    Parameters:
        url (``str``):
            Shortened URL.

        parse_documents (``bool``, *optional*):
            If True, Unalix will also try to obtain the unshortened URL from the response's body.

        **kwargs (``bool``, *optional*):
            Optional arguments that `parse_rules` takes.

    Raises:
        InvalidURL: In case the provided *url* is not a valid URL or hostname.

        InvalidScheme: In case the provided *url* has a invalid or unknown scheme.

    Usage:
      >>> from unalix import unshort_url
      >>> unshort_url("https://bitly.is/Pricing-Pop-Up")
      'https://bitly.com/pages/pricing'
    """
    formated_url = await parse_url(url)
    cleaned_url = await parse_rules(formated_url, **kwargs)
    parsed_url = urllib.parse.urlparse(cleaned_url)

    while True:
        scheme, netloc, path, params, query, fragment = parsed_url
        connection = await creat_connection(scheme, netloc)

        if query:
            path = f"{path}?{query}"

        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        
        if parse_documents:
            content_type = response.headers.get("Content-Type")
        else:
            response.close()
        
        if response.status in redirect_codes:
            location = response.headers.get("Location")
            if location.startswith("http://") or location.startswith("https://"):
                cleaned_url = await parse_rules(location, **kwargs)
                parsed_url = urllib.parse.urlparse(cleaned_url)
            elif location.startswith("/"):
                redirect_url = urllib.parse.urlunparse((scheme, netloc, location, "", "", ""))
                cleaned_url = await parse_rules(redirect_url, **kwargs)
                parsed_url = urllib.parse.urlparse(cleaned_url)
            else:
                path = os.path.join(os.path.dirname(path), location)
                redirect_url = urllib.parse.urlunparse((scheme, netloc, path, "", "", ""))
                cleaned_url = await parse_rules(redirect_url, **kwargs)
                parsed_url = urllib.parse.urlparse(cleaned_url)
        elif parse_documents and mime.match(content_type): # type: ignore
            try:
                extracted_url # type: ignore
            except NameError:
                extracted_url = await extract_url(response, parsed_url.geturl(), **kwargs)
                if not extracted_url is None:
                    parsed_url = urllib.parse.urlparse(extracted_url)
                    continue
            else:
                break
        else:
            break

    if not response.isclosed():
        response.close()

    return parsed_url.geturl()

async def compile_patterns(
    data: list[str],
    replacements: list[tuple[str, str]],
    redirects: list[str]
) -> tuple[list[typing.Any], list[typing.Any], list[typing.Any]]:
    """Compile raw regex patterns into `re.Pattern` instances.

    Parameters:
        data (``list``):
            List containing one or more paths to "data.min.json" files.

        replacements (``list``):
            List containing one or more tuples of raw regex patterns.

        redirects (``list``):
            List containing one or more paths to "body_redirects.json" files.

    Raises:
        InvalidList: In case the provided *files* or *replacements* are not a valid list.
    """
    if not isinstance(data, list) or not data:
        raise InvalidList("Invalid file list")

    if not isinstance(replacements, list) or not replacements:
        raise InvalidList("Invalid replacements list")

    compiled_data = []
    compiled_replacements = []
    compiled_redirects = []

    for filename in data:
        with open(filename, mode="r", encoding="utf-8") as file_object:
            dict_rules = json.loads(file_object.read())
        for provider in dict_rules["providers"].keys():
            (exceptions, redirections, rules, referrals, raws) = ([], [], [], [], [])
            for exception in dict_rules["providers"][provider]["exceptions"]:
                exceptions += [re.compile(exception)]
            for redirection in dict_rules["providers"][provider]["redirections"]:
                redirections += [re.compile(f"{redirection}.*")]
            for common in dict_rules["providers"][provider]["rules"]:
                rules += [re.compile(rf"(%(?:26|23|3[Ff])|&|#|\?){common}(?:(?:=|%3[Dd])[^&]*)")]
            for referral in dict_rules["providers"][provider]["referralMarketing"]:
                referrals += [re.compile(rf"(%(?:26|23|3[Ff])|&|#|\?){referral}(?:(?:=|%3[Dd])[^&]*)")]
            for raw in dict_rules["providers"][provider]["rawRules"]:
                raws += [re.compile(raw)]
            compiled_data += [{
                "pattern": re.compile(dict_rules["providers"][provider]["urlPattern"]),
                "complete": dict_rules["providers"][provider]["completeProvider"],
                "redirection": dict_rules["providers"][provider]["forceRedirection"],
                "exceptions": exceptions,
                "redirections": redirections,
                "rules": rules,
                "referrals": referrals,
                "raws": raws
            }]

    for pattern, replacement in replacements:
        compiled_replacements += [(re.compile(pattern), replacement)]

    for filename in redirects:
        with open(filename, mode="r", encoding="utf-8") as file_object:
            dict_rules = json.loads(file_object.read())
        for rule in dict_rules:
            redirects_list = []
            for raw_pattern in rule["redirects"]:
                redirects_list += [re.compile(f".*{raw_pattern}.*", flags=re.MULTILINE|re.DOTALL)]
            compiled_redirects += [{
                "pattern": re.compile(rule["pattern"]),
                "redirects": redirects_list
            }]

    return (compiled_data, compiled_replacements, compiled_redirects)

async def parse_rules(
    url: str,
    allow_referral: bool = False,
    ignore_rules: bool = False,
    ignore_exceptions: bool = False,
    ignore_raw: bool = False,
    ignore_redirections: bool = False,
    skip_blocked: bool = False,
    skip_local: bool = False
) -> str:
    """Parse compiled regex patterns for the given URL.

    Please take a look at:
        https://github.com/ClearURLs/Addon/wiki/Rules
    to understand how these rules are processed.

    Note that most of the regex patterns contained in the
    "urlPattern", "redirections" and "exceptions" keys expects
    all given URLs to starts with the prefixe "http://" or "https://".

    Parameters:
        url (``str``):
            Some URL with tracking fields.

        allow_referral (``bool``, *optional*):
            Pass True to ignore regex rules targeting marketing fields.

        ignore_rules (``bool``, *optional*):
            Pass True to ignore regex rules from "rules" keys.

        ignore_exceptions (``bool``, *optional*):
            Pass True to ignore regex rules from "exceptions" keys.

        ignore_raw (``bool``, *optional*):
            Pass True to ignore regex rules from "rawRules" keys.

        ignore_redirections (``bool``, *optional*):
            Pass True to ignore regex rules from "redirections" keys.

        skip_blocked (``bool``, *optional*):
            Pass True to skip/ignore regex rules for blocked domains.

        skip_local (``bool``, *optional*):
            Pass True to skip URLs on local/private hosts (e.g 127.0.0.1, 0.0.0.0, localhost).

    Usage:
      >>> from unalix._utils import parse_rules
      >>> parse_rules("http://g.co/?utm_source=google")
      'http://g.co/'
    """
    if skip_local and is_private(url):
        return url

    for pattern in patterns:
        if skip_blocked and pattern["complete"]:
            continue
        (original_url, skip_provider) = (url, False)
        if pattern["pattern"].match(url):
            if not ignore_exceptions:
                for exception in pattern["exceptions"]:
                    if exception.match(url):
                        skip_provider = True
                        break
            if skip_provider:
                continue
            if not ignore_redirections:
                for redirection in pattern["redirections"]:
                    url = redirection.sub(r"\g<1>", url)
                if url != original_url:
                    url = urllib.parse.unquote(url)
                    url = await requote_uri(url)
            if not ignore_rules:
                for rule in pattern["rules"]:
                    url = rule.sub(r"\g<1>", url)
            if not allow_referral:
                for referral in pattern["referrals"]:
                    url = referral.sub(r"\g<1>", url)
            if not ignore_raw:
                for raw in pattern["raws"]:
                    url = raw.sub("", url)
            original_url = url

    for pattern, replacement in replacements:
        url = pattern.sub(replacement, url)

    return url

(patterns, replacements, redirects) = loop.run_until_complete(compile_patterns(paths_data, replacements, paths_redirects))
context = loop.run_until_complete(creat_ssl_context())