"""Compose HTML emails using Jinja2 templates."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import BacktestReport, SchedulePeriod

logger = logging.getLogger(__name__)

# Default template directory relative to this file
DEFAULT_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


class EmailComposer:
    """Compose HTML emails from backtest reports."""

    def __init__(self, template_dir: Optional[str] = None):
        template_path = Path(template_dir) if template_dir else DEFAULT_TEMPLATE_DIR

        self.env = Environment(
            loader=FileSystemLoader(str(template_path)),
            autoescape=select_autoescape(["html", "xml"]),
        )

        # Register custom filters
        self.env.filters["format_number"] = self._format_number
        self.env.filters["format_currency"] = self._format_currency
        self.env.filters["format_pct"] = self._format_pct
        self.env.filters["format_datetime"] = self._format_datetime
        self.env.filters["format_datetime_full"] = self._format_datetime_full
        self.env.filters["format_time"] = self._format_time

    @staticmethod
    def _format_number(value: float, decimals: int = 2) -> str:
        """Format number with thousands separator."""
        if value is None:
            return "-"
        return f"{value:,.{decimals}f}"

    @staticmethod
    def _format_currency(value: float, decimals: int = 2) -> str:
        """Format as currency with $ sign."""
        if value is None:
            return "-"
        sign = "+" if value > 0 else ""
        return f"{sign}${value:,.{decimals}f}"

    @staticmethod
    def _format_pct(value: float, decimals: int = 1) -> str:
        """Format as percentage."""
        if value is None:
            return "-"
        return f"{value:.{decimals}f}%"

    @staticmethod
    def _format_datetime(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
        """Format datetime."""
        if dt is None:
            return "-"
        return dt.strftime(fmt)

    @staticmethod
    def _format_datetime_full(dt: datetime) -> str:
        """Format datetime with full date and time (Apr 3, 2026 14:30 UTC)."""
        if dt is None:
            return "-"
        return dt.strftime("%b %d, %Y %H:%M UTC")

    @staticmethod
    def _format_time(dt: datetime) -> str:
        """Format time only (HH:MM)."""
        if dt is None:
            return "-"
        return dt.strftime("%H:%M")

    def _period_label(self, period: SchedulePeriod) -> str:
        """Get human-readable period label."""
        return {
            SchedulePeriod.DAILY: "Daily",
            SchedulePeriod.WEEKLY: "Weekly",
            SchedulePeriod.MONTHLY: "Monthly",
        }.get(period, "Unknown")

    def _period_date_range(self, report: BacktestReport) -> str:
        """Format period date range based on period type."""
        start = report.period_start
        end = report.period_end

        if report.period == SchedulePeriod.DAILY:
            # Show single day range: Apr 3-4, 2026
            return f"{start.strftime('%b %d')}-{end.strftime('%d, %Y')}"
        elif report.period == SchedulePeriod.WEEKLY:
            # Show week range: Mar 28 - Apr 4, 2026
            return f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"
        else:
            # Show month range: Mar 4 - Apr 4, 2026
            return f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"

    def compose(
        self, report: BacktestReport, template_name: str = "scheduled_report.html"
    ) -> str:
        """
        Compose HTML email from report.

        Args:
            report: The backtest report to render
            template_name: Name of the template file

        Returns:
            Rendered HTML string (minified to avoid Gmail clipping)
        """
        template = self.env.get_template(template_name)

        context = {
            "report": report,
            "period_label": self._period_label(report.period),
            "period_date_range": self._period_date_range(report),
            "generated_at": report.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

        html = template.render(**context)

        # Minify HTML to reduce size and avoid Gmail clipping
        import re
        # Remove extra whitespace between tags
        html = re.sub(r'>\s+<', '><', html)
        # Remove leading/trailing whitespace on lines
        html = re.sub(r'\n\s+', '\n', html)
        # Collapse multiple newlines
        html = re.sub(r'\n+', '\n', html)

        return html.strip()

    def compose_subject(self, report: BacktestReport) -> str:
        """Compose email subject line."""
        period_label = self._period_label(report.period)
        date_str = report.period_end.strftime("%Y-%m-%d")

        pnl_sign = "+" if report.total_net_pnl >= 0 else ""
        pnl_str = f"{pnl_sign}${report.total_net_pnl:,.2f}"

        return (
            f"[{period_label} Backtest] {report.symbol} | "
            f"{pnl_str} | {date_str}"
        )
