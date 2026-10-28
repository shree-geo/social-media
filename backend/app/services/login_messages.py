"""Ready-to-paste login message for WhatsApp/email (ONBOARDING_AND_CHANNEL_SETUP.md §3.2)."""

from datetime import datetime


def share_message(
    *, app_name: str, login_url: str, full_name: str, email: str, temporary_password: str, expires_at: datetime
) -> str:
    expires = expires_at.strftime("%Y-%m-%d")
    return (
        f"Hello {full_name}! Your {app_name} account is ready.\n"
        f"Login: {login_url}\n"
        f"Email: {email}\n"
        f"Temporary password: {temporary_password}\n"
        f"Please log in before {expires} and set your own password.\n"
        "\n"
        f"नमस्ते {full_name}! तपाईंको {app_name} खाता तयार छ।\n"
        f"लगइन: {login_url}\n"
        f"इमेल: {email}\n"
        f"अस्थायी पासवर्ड: {temporary_password}\n"
        f"कृपया {expires} भित्र लगइन गरी आफ्नै पासवर्ड राख्नुहोस्।"
    )
