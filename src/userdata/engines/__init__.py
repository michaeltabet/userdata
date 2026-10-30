"""Storage engines behind two interfaces: transactional and analytical.

Tools and services never name an engine. `open_oltp` and `open_olap` pick the
class from the Config (SDD rule 3 and section 8).
"""

from userdata import config as config_lib
from userdata.engines import olap
from userdata.engines import oltp

_OLTP = {"sqlite": oltp.SqliteEngine}
_OLAP = {"duckdb": olap.DuckDbEngine}


def open_oltp(config: config_lib.Config) -> oltp.OltpEngine:
    """Opens the transactional store named in the config.

    Args:
        config: The server configuration.

    Returns:
        A connected OLTP engine.

    Raises:
        ValueError: If the engine name is unknown.
    """
    try:
        engine_cls = _OLTP[config.oltp_engine]
    except KeyError as exc:
        raise ValueError(f"unknown OLTP engine {config.oltp_engine!r}") from exc
    return engine_cls(config)


def open_olap(config: config_lib.Config) -> olap.OlapEngine:
    """Opens the analytical store named in the config.

    Args:
        config: The server configuration.

    Returns:
        A connected OLAP engine.

    Raises:
        ValueError: If the engine name is unknown.
    """
    try:
        engine_cls = _OLAP[config.olap_engine]
    except KeyError as exc:
        raise ValueError(f"unknown OLAP engine {config.olap_engine!r}") from exc
    return engine_cls(config)
