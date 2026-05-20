from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import httpx


@dataclass
class WhatsAppClientError(Exception):
    message: str
    status_code: int | None = None
    provider_error_code: str | None = None
    provider_error_subcode: str | None = None
    response_body: str | None = None

    def __str__(self) -> str:
        return self.message


class WhatsAppCloudClient:
    def __init__(self, *, base_url: str = "https://graph.facebook.com") -> None:
        self.base_url = base_url.rstrip("/")

    async def _post(self, *, path: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        url = f"{self.base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text
                err = exc.response.json().get("error", {}) if exc.response.content else {}
                raise WhatsAppClientError(
                    message="Meta API request failed",
                    status_code=exc.response.status_code,
                    provider_error_code=str(err.get("code")) if err.get("code") is not None else None,
                    provider_error_subcode=str(err.get("error_subcode")) if err.get("error_subcode") is not None else None,
                    response_body=body,
                ) from exc

    async def _get(self, *, path: str, token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{self.base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    async def send_text(self, *, api_version: str, phone_number_id: str, token: str, to: str, body: str) -> dict[str, Any]:
        return await self._post(
            path=f"{api_version}/{phone_number_id}/messages",
            token=token,
            payload={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": body},
            },
        )

    async def send_template(self, *, api_version: str, phone_number_id: str, token: str, to: str, name: str, language: str, components: list[dict] | None = None) -> dict[str, Any]:
        return await self._post(
            path=f"{api_version}/{phone_number_id}/messages",
            token=token,
            payload={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": name,
                    "language": {"code": language},
                    **({"components": components} if components else {}),
                },
            },
        )

    async def send_media(self, *, api_version: str, phone_number_id: str, token: str, to: str, media_type: str, media_ref: str, caption: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"messaging_product": "whatsapp", "to": to, "type": media_type, media_type: {"id": media_ref}}
        if caption:
            payload[media_type]["caption"] = caption
        return await self._post(path=f"{api_version}/{phone_number_id}/messages", token=token, payload=payload)

    async def send_interactive_buttons(self, *, api_version: str, phone_number_id: str, token: str, to: str, body_text: str, buttons: list[dict]) -> dict[str, Any]:
        return await self._post(
            path=f"{api_version}/{phone_number_id}/messages",
            token=token,
            payload={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body_text},
                    "action": {"buttons": buttons},
                },
            },
        )

    async def send_list(self, *, api_version: str, phone_number_id: str, token: str, to: str, body_text: str, button_text: str, sections: list[dict]) -> dict[str, Any]:
        return await self._post(
            path=f"{api_version}/{phone_number_id}/messages",
            token=token,
            payload={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": body_text},
                    "action": {"button": button_text, "sections": sections},
                },
            },
        )

    async def send_location(self, *, api_version: str, phone_number_id: str, token: str, to: str, latitude: float, longitude: float, name: str | None = None, address: str | None = None) -> dict[str, Any]:
        return await self._post(
            path=f"{api_version}/{phone_number_id}/messages",
            token=token,
            payload={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "location",
                "location": {
                    "latitude": latitude,
                    "longitude": longitude,
                    **({"name": name} if name else {}),
                    **({"address": address} if address else {}),
                },
            },
        )

    async def send_contacts(self, *, api_version: str, phone_number_id: str, token: str, to: str, contacts: list[dict]) -> dict[str, Any]:
        return await self._post(
            path=f"{api_version}/{phone_number_id}/messages",
            token=token,
            payload={"messaging_product": "whatsapp", "to": to, "type": "contacts", "contacts": contacts},
        )

    async def send_reaction(self, *, api_version: str, phone_number_id: str, token: str, to: str, message_id: str, emoji: str) -> dict[str, Any]:
        return await self._post(
            path=f"{api_version}/{phone_number_id}/messages",
            token=token,
            payload={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "reaction",
                "reaction": {"message_id": message_id, "emoji": emoji},
            },
        )

    async def mark_as_read(self, *, api_version: str, phone_number_id: str, token: str, message_id: str) -> dict[str, Any]:
        return await self._post(
            path=f"{api_version}/{phone_number_id}/messages",
            token=token,
            payload={"messaging_product": "whatsapp", "status": "read", "message_id": message_id},
        )

    async def upload_media(self, *, api_version: str, phone_number_id: str, token: str, link: str, media_type: str) -> dict[str, Any]:
        return await self._post(
            path=f"{api_version}/{phone_number_id}/media",
            token=token,
            payload={"messaging_product": "whatsapp", "type": media_type, "link": link},
        )

    async def download_media(self, *, media_id: str, token: str) -> dict[str, Any]:
        return await self._get(path=f"{media_id}", token=token)

    async def get_message_status(self, *, message_id: str, token: str, fields: str = "id,status,timestamp") -> dict[str, Any]:
        return await self._get(path=message_id, token=token, params={"fields": fields})


whatsapp_cloud_client = WhatsAppCloudClient()

