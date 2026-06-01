"""Google OAuth id_token verification via the tokeninfo endpoint."""
import httpx

TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


async def verify_google_token(id_token: str, client_id: str) -> dict:
    """Validate a Google id_token and return the decoded claims.

    Args:
        id_token: The raw id_token string received from the frontend after
                  the user completes the Google sign-in flow.
        client_id: The OAuth 2.0 client ID that the token must be issued for.

    Returns:
        A dict with at least: sub, email, name, email_verified, picture.

    Raises:
        ValueError: If the request fails, the token is invalid, the audience
                    does not match, or the email is not verified.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            TOKENINFO_URL,
            params={"id_token": id_token},
        )

    if response.status_code != 200:
        raise ValueError(
            f"Google tokeninfo retornou status {response.status_code}: {response.text}"
        )

    claims: dict = response.json()

    # Validate audience (aud) to prevent token substitution attacks
    aud = claims.get("aud", "")
    if aud != client_id:
        raise ValueError(
            f"Token audience '{aud}' não corresponde ao client_id configurado."
        )

    # Validate that the email has been verified by Google
    email_verified = claims.get("email_verified", "false")
    if str(email_verified).lower() != "true":
        raise ValueError("Email do Google não verificado.")

    return claims
