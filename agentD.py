import logging
import smtplib
from email.message import EmailMessage
from typing import Dict, List, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

VAULT_URL = "https://app.hyperliquid.xyz/vaults/0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"
THRESHOLD = 50_000

EMAIL_USER = "cryptosscalp@gmail.com"
EMAIL_PASS = "gfke olcu ulud zpnh"
ALERT_EMAIL = "25harshitgarg12345@gmail.com"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

TABLE_EXTRACTION_SCRIPT = """
() => {
  const tables = Array.from(document.querySelectorAll('table'));
  for (const table of tables) {
    const headers = Array.from(table.querySelectorAll('th')).map(th => th.textContent.trim());
    if (!headers.length) continue;
    if (headers.includes('Position Value (USDC)') && headers.includes('Coin')) {
      let rows = Array.from(table.querySelectorAll('tbody tr'));
      if (!rows.length) {
        const allRows = Array.from(table.querySelectorAll('tr'));
        rows = allRows.slice(1);
      }
      return rows.map(row => {
        const cells = Array.from(row.querySelectorAll('td')).map(td => td.textContent.trim());
        const record = {};
        headers.forEach((header, idx) => {
          record[header] = cells[idx] ?? '';
        });
        return record;
      });
    }
  }
  return [];
}
"""


def parse_currency(value_str: str) -> Optional[float]:
    if not value_str:
        return None
    cleaned = (
        value_str.replace(",", "")
        .replace("$", "")
        .replace("USDC", "")
        .strip()
    )
    try:
        return float(cleaned)
    except ValueError:
        logging.debug("Unparseable currency string: %s", value_str)
        return None


def fetch_positions() -> List[Dict[str, str]]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            logging.info("Opening vault page: %s", VAULT_URL)
            page.goto(VAULT_URL, wait_until="networkidle")
            page.wait_for_selector("text=Position Value (USDC)", timeout=15000)
            rows = page.evaluate(TABLE_EXTRACTION_SCRIPT) or []
            logging.info("Extracted %d PERP rows", len(rows))
            return rows
        except PlaywrightTimeoutError as exc:
            logging.error("Timed out waiting for the PERP table: %s", exc)
            raise
        finally:
            context.close()
            browser.close()


def normalize_positions(raw_rows: List[Dict[str, str]]) -> List[Dict[str, Optional[float]]]:
    positions = []
    for row in raw_rows:
        coin = row.get("Coin", "").strip()
        position_value_raw = row.get("Position Value (USDC)", "").strip()
        if not coin or not position_value_raw:
            continue
        position_value = parse_currency(position_value_raw)
        if position_value is None:
            continue
        positions.append(
            {
                "coin": coin,
                "size": row.get("Size", "").strip(),
                "position_value_raw": position_value_raw,
                "position_value": position_value,
                "mark_price": row.get("Mark Price", "").strip(),
            }
        )
    return positions


def collect_alerts(positions: List[Dict[str, Optional[float]]]) -> List[Dict[str, Optional[float]]]:
    return [
        pos for pos in positions
        if pos["position_value"] and pos["position_value"] > THRESHOLD
    ]


def build_email_body(alerts: List[Dict[str, Optional[float]]]) -> str:
    lines = ["🚨 PERP Position Exceeds \$50,000 🚨", ""]
    for alert in alerts:
        lines.append(
            f"{alert['coin']} 20x | Value: {alert['position_value_raw']} | "
            f"Size: {alert['size']} | Mark: {alert['mark_price']}"
        )
    lines.extend(["", f"Vault: {VAULT_URL}"])
    return "\n".join(lines)


def send_email(alerts: List[Dict[str, Optional[float]]]) -> None:
    message = EmailMessage()
    message["Subject"] = "🚨 PERP Position Exceeds \$50,000 🚨"
    message["From"] = EMAIL_USER
    message["To"] = ALERT_EMAIL
    message.set_content(build_email_body(alerts))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(message)
        logging.info("Alert email sent to %s", ALERT_EMAIL)
    except smtplib.SMTPException:
        logging.exception("Failed to send alert email.")
        raise


def main() -> None:
    logging.info("Starting PERP monitor.")
    raw_rows = fetch_positions()
    positions = normalize_positions(raw_rows)
    alerts = collect_alerts(positions)

    if not alerts:
        logging.info("No PERP position exceeds \$50,000; email skipped.")
        return

    send_email(alerts)


if __name__ == "__main__":
    main()
