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
SUBJECT = "You're on the Libas AI list"

# Hosted from the frontend's own static assets (frontend/public/email-
# logo-badge.png - the hanger mark on a white circular badge, swapped in
# for the earlier flat-white-icon-on-olive version, which read as plain).
# Gmail's colored-letter SENDER AVATAR (the circle next to "Libas AI" in
# the inbox list, not anything inside this template) is a separate thing
# entirely: either the sender's actual Google Account profile photo (if
# team@ is a real Google Workspace mailbox - just set a photo on that
# account, free, no DNS) or, for non-Gmail recipients, BIMI (a verified-
# logo DNS record that requires DMARC enforcement first). Not done here,
# deliberately - enforcing DMARC on a brand-new sending domain before its
# reputation is established risks legitimate mail getting rejected.
LOGO_BADGE_URL = "https://libasai.com/email-logo-badge.png"

# "One search box" undersold this as keyword search - it's natural-
# language search (describe what you want in plain English, no filters to
# click through), so the copy now says that explicitly and leads with the
# one line specifically asked for: "Describe what you want and Libas AI
# will find it for you." Table-based layout (not div/flexbox) for
# Outlook's Word rendering engine, a hidden preheader so the inbox preview
# line isn't blank/random, and a forced "light only" color-scheme so
# Gmail/Apple Mail dark mode never re-colors the olive brand band.
_TEXT_BODY = (
    "You're on the Libas AI list.\n\n"
    "Libas AI is natural-language search across every Pakistani clothing "
    "brand's catalog. Describe what you want and Libas AI will find it "
    "for you.\n\n"
    "We'll email you once, when it goes live. Nothing else.\n\n"
    "Questions, or a brand you want us to include? Just reply to this email.\n\n"
    "The Libas AI team\n\n"
    "---\n"
    "You're getting this because you signed up at libasai.com.\n"
    "Libas AI - Islamabad, Pakistan - team@libasai.com"
)
_HTML_BODY = f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light only">
<title>You're on the Libas AI list</title>
</head>
<body style="margin:0;padding:0;background:#F5F4F0;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">
  You're on the list. We'll email you once, when Libas AI goes live.
</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F5F4F0;">
  <tr>
    <td align="center" style="padding:40px 16px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;background:#FFFFFF;border-radius:14px;overflow:hidden;">

        <!-- Brand band -->
        <tr>
          <td align="center" bgcolor="#4E5836" style="background:#4E5836;padding:40px 32px 36px 32px;">
            <img src="{LOGO_BADGE_URL}" width="64" height="64" alt="Libas AI" style="display:block;border:0;margin:0 auto 14px auto;">
            <div style="font-family:Arial,Helvetica,sans-serif;font-size:20px;font-weight:bold;color:#FFFFFF;letter-spacing:0.2px;">
              Libas AI
            </div>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:36px 36px 8px 36px;font-family:Arial,Helvetica,sans-serif;color:#1A1A1A;">
            <h1 style="margin:0 0 16px 0;font-size:26px;line-height:1.25;font-weight:bold;">
              You're on the list.
            </h1>
            <p style="margin:0 0 24px 0;font-size:16px;line-height:1.6;color:#3D3D3D;">
              Libas AI is natural-language search across every Pakistani clothing brand's catalog.
              <strong>Describe what you want and Libas AI will find it for you.</strong>
            </p>
          </td>
        </tr>

        <!-- Closing -->
        <tr>
          <td style="padding:0 36px;font-family:Arial,Helvetica,sans-serif;">
            <p style="margin:0 0 12px 0;font-size:16px;line-height:1.6;color:#3D3D3D;">
              We'll email you once, when it goes live. Nothing else.
            </p>
            <p style="margin:0;font-size:16px;line-height:1.6;color:#3D3D3D;">
              Questions, or a brand you want us to include? Just reply to this email.
            </p>
          </td>
        </tr>

        <tr>
          <td style="padding:24px 36px 36px 36px;font-family:Arial,Helvetica,sans-serif;font-size:16px;font-weight:bold;color:#4E5836;">
            The Libas AI team
          </td>
        </tr>
      </table>

      <!-- Footer -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
        <tr>
          <td align="center" style="padding:20px 32px 0 32px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.6;color:#8A8A85;">
            You're getting this because you signed up at
            <a href="https://libasai.com" style="color:#8A8A85;">libasai.com</a>.<br>
            Libas AI &middot; Islamabad, Pakistan &middot;
            <a href="mailto:team@libasai.com" style="color:#8A8A85;">team@libasai.com</a>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>
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
