"""SMTP email sender."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from .models import SMTPConfig

logger = logging.getLogger(__name__)


class EmailSender:
    """Send emails via SMTP."""

    def __init__(self, config: SMTPConfig):
        self.config = config

    def send(
        self,
        recipients: List[str],
        subject: str,
        html_body: str,
        text_body: str = "",
    ) -> bool:
        """
        Send an email.

        Args:
            recipients: List of recipient email addresses
            subject: Email subject
            html_body: HTML content of the email
            text_body: Plain text fallback (optional)

        Returns:
            True if email was sent successfully
        """
        if not recipients:
            logger.warning("No recipients specified, skipping email send")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = (
                f"{self.config.from_name} <{self.config.from_address}>"
                if self.config.from_name
                else self.config.from_address
            )
            msg["To"] = ", ".join(recipients)

            # Attach plain text version if provided
            if text_body:
                text_part = MIMEText(text_body, "plain")
                msg.attach(text_part)

            # Attach HTML version
            html_part = MIMEText(html_body, "html")
            msg.attach(html_part)

            # Connect and send
            if self.config.use_tls:
                server = smtplib.SMTP(self.config.host, self.config.port)
                server.starttls()
            else:
                server = smtplib.SMTP(self.config.host, self.config.port)

            server.login(self.config.username, self.config.password)
            server.sendmail(
                self.config.from_address,
                recipients,
                msg.as_string(),
            )
            server.quit()

            logger.info(
                f"Email sent successfully to {len(recipients)} recipients: {subject}"
            )
            return True

        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending email: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False

    def test_connection(self) -> bool:
        """Test SMTP connection without sending an email."""
        try:
            if self.config.use_tls:
                server = smtplib.SMTP(self.config.host, self.config.port)
                server.starttls()
            else:
                server = smtplib.SMTP(self.config.host, self.config.port)

            server.login(self.config.username, self.config.password)
            server.quit()

            logger.info("SMTP connection test successful")
            return True

        except smtplib.SMTPException as e:
            logger.error(f"SMTP connection test failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Connection test error: {e}")
            return False
