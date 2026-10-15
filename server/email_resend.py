"""Resend (resend.com) transactional email - the coming-soon page's only
outbound email. Free tier (3,000/month, 100/day) comfortably covers a
pre-launch signup list; chosen over AWS SES specifically because SES
requires Amazon to manually approve production sending (can take a day+)
before it will email anyone who has not individually verified their own
address first - unusable for a public signup form on day one.

Fire-and-forget: called from a BackgroundTask (see routes/signups.py), so
a Resend outage or hitting the free-tier cap never fails the signup
itself - it is just logged.
"""
import logging
import os

import httpx

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
FROM_ADDRESS = "Libas AI <team@libasai.com>"
SUBJECT = "You're on the list"

# Same voice and color tokens as the coming-soon page itself (frontend/src/
# styles/index.css's --bg/--text/--text-soft/--text-faint/--accent-strong)
# rather than default email-client styling, so this doesn't read as generic
# transactional boilerplate. Inline styles only - email clients strip
# <style> blocks and external CSS.
_TEXT_BODY = (
    "Thanks for your interest in Libas AI.\n\n"
    "We're rebuilding it from the ground up: one search box, every brand's "
    "catalog. You'll get an email the moment it's live.\n\n"
    "Libas AI"
)
# Hosted from the frontend's own static assets (frontend/public/email-
# logo.png, the same hanger mark as the favicon/navbar/videos) - Gmail's
# colored-letter avatar next to the sender name is a separate thing
# entirely (controlled by BIMI + enforced DMARC, not by anything in this
# email), not worth the DNS/deliverability risk for a pre-launch
# placeholder, so this is the lever that's actually in our control.
LOGO_URL = "https://libasai.com/email-logo.png"

_HTML_BODY = f"""\
<div style="background:#f7f7f5;padding:48px 20px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:420px;margin:0 auto;background:#ffffff;border:1px solid #e4e4e1;border-radius:14px;padding:40px 32px;text-align:center;">
    <img src="{LOGO_URL}" width="40" height="40" alt="Libas AI" style="display:block;margin:0 auto 20px;" />
    <p style="font-size:16px;line-height:1.5;color:#14161a;font-weight:600;margin:0 0 16px;">
      Thanks for your interest in Libas AI.
    </p>
    <p style="font-size:14.5px;line-height:1.6;color:#63665f;margin:0 0 24px;">
      We're rebuilding it from the ground up.
      <span style="color:#4e5836;font-weight:600;">One search box, every brand's catalog.</span>
      You'll get an email the moment it's live.
    </p>
    <p style="font-size:12.5px;color:#96988f;margin:0;">
      <a href="mailto:team@libasai.com" style="color:#96988f;text-decoration:none;">team@libasai.com</a>
    </p>
  </div>
</div>
"""

logger = logging.getLogger("libas")


async def send_signup_confirmation(email: str) -> None:
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured, skipping confirmation email to %s", email)
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={
                    "from": FROM_ADDRESS,
                    "to": [email],
                    "subject": SUBJECT,
                    "html": _HTML_BODY,
                    "text": _TEXT_BODY,
                },
            )
        if resp.status_code >= 400:
            logger.warning("Resend send failed (%s) for %s: %s", resp.status_code, email, resp.text)
    except Exception:
        logger.exception("Resend send errored for %s", email)
