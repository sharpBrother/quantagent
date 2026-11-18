"""WGC 主报告 HTML 的季度供需解析，沿用旧仓 Gold Balance 口径。"""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from quantagent.ingest.errors import SourceFetchError

LISTING_URL = "https://www.gold.org/goldhub/research/gold-demand-trends"
_YEAR_PIVOT = 80
_LABELS = {
    "mine production": "MINE_PRODUCTION",
    "net producer hedging": "NET_PRODUCER_HEDGING",
    "recycled gold": "RECYCLED_GOLD",
    "total supply": "TOTAL_SUPPLY",
    "jewellery fabrication": "JEWELLERY_FABRICATION",
    "jewellery consumption": "JEWELLERY_CONSUMPTION",
    "jewellery inventory": "JEWELLERY_INVENTORY",
    "technology": "TECHNOLOGY",
    "electronics": "ELECTRONICS",
    "other industrial": "OTHER_INDUSTRIAL",
    "dentistry": "DENTISTRY",
    "investment": "INVESTMENT",
    "total bar and coin": "TOTAL_BAR_AND_COIN",
    "bars": "BARS",
    "physical bar demand": "BARS",
    "official coins": "OFFICIAL_COINS",
    "medals/imitation coins": "MEDALS_IMITATION_COINS",
    "medals imitation coins": "MEDALS_IMITATION_COINS",
    "etfs and similar products": "ETFS_SIMILAR_PRODUCTS",
    "central banks and other inst.": "CENTRAL_BANK_OTHER",
    "central bank and other institutions": "CENTRAL_BANK_OTHER",
    "gold demand": "GOLD_DEMAND",
    "otc and other": "OTC_OTHER",
    "total demand": "TOTAL_DEMAND",
}


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.times: list[str] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")
        elif tag == "time" and (value := dict(attrs).get("datetime")):
            self.times.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)


def latest_report_url(html: str) -> str:
    marker = "Read the latest Gold Demand Trends"
    index = html.find(marker)
    if index < 0:
        raise SourceFetchError("WGC 目录缺少最新报告链接")
    hrefs = re.findall(r'href="([^"]+)"', html[max(0, index - 1200) : index])
    if not hrefs:
        raise SourceFetchError("WGC 最新报告缺少链接")
    url = urljoin(LISTING_URL, hrefs[-1])
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.gold.org"
        or "gold-demand-trends" not in parsed.path
        or any(
            x in parsed.path.lower()
            for x in ("us-focus", "india-focus", "-zh", "-jp", "-ja", "focus-q")
        )
    ):
        raise SourceFetchError("WGC 最新链接不是主报告")
    return str(url)


def parse_report(html: str) -> tuple[str, str, list[tuple[str, str, Decimal]]]:  # noqa: PLR0912
    parser = _Tables()
    parser.feed(html)
    if not parser.times or not parser.tables or not parser.tables[0]:
        raise SourceFetchError("WGC 报告缺少发布日期或数据表")
    try:
        publish = datetime.fromisoformat(parser.times[0].replace("Z", "+00:00")).strftime("%Y%m%d")
    except ValueError:
        raise SourceFetchError("WGC 报告发布日期无效") from None
    table = parser.tables[0]
    periods = {}
    for col, cell in enumerate(table[0]):
        match = re.fullmatch(r"Q([1-4])['’](\d{2})", re.sub(r"\s+", "", cell), re.I)
        if match:
            year = int(match[2])
            # 旧仓季度标题约定：80–99 属于 20 世纪。
            year += 2000 if year < _YEAR_PIVOT else 1900
            month = int(match[1]) * 3
            periods[col] = f"{year:04d}{month:02d}{calendar.monthrange(year, month)[1]:02d}"
    if not periods or len(set(periods.values())) != len(periods):
        raise SourceFetchError("WGC 报告季度列缺失或重复")
    found: dict[str, list[str]] = {}
    for row in table[1:]:
        label = re.sub(r"\s+", " ", row[0]).strip().lower().replace("&", "and") if row else ""
        category = _LABELS.get(label)
        if category:
            if category in found:
                raise SourceFetchError(f"WGC 类别重复: {category}")
            found[category] = row
    if set(found) != set(_LABELS.values()):
        raise SourceFetchError("WGC 报告供需类别不完整")
    result = []
    for category, row in sorted(found.items()):
        for col, period in sorted(periods.items()):
            try:
                value = Decimal(row[col].strip().replace(",", "").replace("%", ""))
                if not value.is_finite():
                    raise ValueError
                value = value.quantize(Decimal("0.00000001"))
            except (IndexError, InvalidOperation, ValueError):
                raise SourceFetchError(f"WGC 数值缺失或无效: {category} {period}") from None
            result.append((period, category, value))
    return publish, hashlib.sha256(html.encode("utf-8")).hexdigest(), result


def fetch_latest_report() -> tuple[str, str, list[tuple[str, str, Decimal]]]:
    try:
        headers = {"User-Agent": "QuantAgent gold-timing research"}
        listing = requests.get(LISTING_URL, headers=headers, timeout=30)
        listing.raise_for_status()
        report = requests.get(latest_report_url(listing.text), headers=headers, timeout=30)
        report.raise_for_status()
    except requests.RequestException as exc:
        raise SourceFetchError(f"WGC 请求失败: {type(exc).__name__}") from None
    return parse_report(report.content.decode("utf-8", "replace"))
