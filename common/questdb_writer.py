import logging
import time
from typing import Optional
from urllib import error, request

from common.interface_book import PriceLevel


class QuestDbWriter:
    """
    Simple QuestDB writer using ILP over HTTP.

    Expected payload fields:
    - venue
    - symbol
    - bid
    - ask
    - bid_size
    - ask_size
    - received_timestamp_epoch
    - stamping_timestamp_epoch
    """

    def __init__(
            self,
            host: str = "localhost",
            port: int = 9000,
            table: str = "market_quotes",
            timeout_seconds: float = 10
    ):
        self.host = host
        self.port = port
        self.table = table
        self.timeout_seconds = timeout_seconds

        self._base_url = f"http://{self.host}:{self.port}"

    @staticmethod
    def _to_ns(epoch_value: int | float) -> int:
        value = float(epoch_value)
        # Heuristic: <= 10^10 is likely seconds, <= 10^13 is likely milliseconds
        if value <= 10_000_000_000:
            return int(value * 1_000_000_000)
        if value <= 10_000_000_000_000:
            return int(value * 1_000_000)
        return int(value)

    @staticmethod
    def _escape_tag_value(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ").replace("=", "\\=")

    @staticmethod
    def _escape_measurement(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ")

    def _post_lines(self, lines: str) -> bool:
        if not lines:
            return True
        url = f"{self._base_url}/write?precision=n"
        body = lines.encode("utf-8")
        req = request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "text/plain; charset=utf-8")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds):
                pass
            return True
        except (error.URLError, error.HTTPError) as e:
            logging.error("QuestDB HTTP write failed: %s", e)
            return False
        except Exception as e:
            logging.exception("QuestDB HTTP write exception: %s", e)
            return False

    def write_order_book(
            self,
            venue: str,
            symbol: str,
            bids: list[PriceLevel],
            asks: list[PriceLevel],
            received_timestamp_epoch: int | float,
            stamping_timestamp_epoch: Optional[int | float] = None,
    ) -> bool:
        """
        Store a full depth order book of arbitrary, uneven size.

        Each price level becomes one row with:
        - venue (tag)
        - symbol (tag)
        - side ("bid" or "ask" as field)
        - level_index (field, 0-based per side)
        - price (field)
        - size (field)
        - received_timestamp (field, ns)
        - stamping_timestamp (field, ns)
        - line timestamp = stamping_timestamp
        """

        if stamping_timestamp_epoch is None:
            stamping_timestamp_epoch = int(time.time() * 1000)

        received_ns = self._to_ns(received_timestamp_epoch)
        stamping_ns = self._to_ns(stamping_timestamp_epoch)

        if not bids and not asks:
            return True

        measurement = self._escape_measurement(self.table)
        tag_venue = self._escape_tag_value(venue)
        tag_symbol = self._escape_tag_value(symbol)

        lines: list[str] = []
        for idx, level in enumerate(bids):
            lines.append(
                f"{measurement},venue={tag_venue},symbol={tag_symbol},side=bid "
                f"level_index={idx}i,price={float(level.price)},size={float(level.size)},"
                f"received_timestamp={received_ns}i,stamping_timestamp={stamping_ns}i {stamping_ns}"
            )

        for idx, level in enumerate(asks):
            lines.append(
                f"{measurement},venue={tag_venue},symbol={tag_symbol},side=ask "
                f"level_index={idx}i,price={float(level.price)},size={float(level.size)},"
                f"received_timestamp={received_ns}i,stamping_timestamp={stamping_ns}i {stamping_ns}"
            )

        return self._post_lines("\n".join(lines))
