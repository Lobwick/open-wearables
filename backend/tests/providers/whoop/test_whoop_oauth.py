"""Whoop token refresh request."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.providers.whoop.oauth import WhoopOAuth


def _oauth() -> WhoopOAuth:
    return WhoopOAuth(
        user_repo=MagicMock(),
        connection_repo=MagicMock(),
        provider_name="whoop",
        api_base_url="https://api.prod.whoop.com",
    )


def test_refresh_request_asks_for_the_offline_scope() -> None:
    data, headers = _oauth()._prepare_refresh_request("old-rt")

    # Whoop documents all of these as required on a refresh, scope included.
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "old-rt"
    assert data["scope"] == "offline"
    assert "client_id" in data
    assert "client_secret" in data
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"


@patch("app.services.providers.templates.base_oauth.httpx.post")
def test_refresh_posts_the_scope_to_the_token_endpoint(mock_post: MagicMock) -> None:
    mock_post.return_value.json.return_value = {
        "access_token": "new-at",
        "refresh_token": "new-rt",
        "expires_in": 3600,
        "token_type": "bearer",
    }
    oauth = _oauth()

    token = oauth.refresh_access_token(MagicMock(), uuid4(), "old-rt")

    assert token.access_token == "new-at"
    assert mock_post.call_args.args[0] == "https://api.prod.whoop.com/oauth/oauth2/token"
    assert mock_post.call_args.kwargs["data"]["scope"] == "offline"
