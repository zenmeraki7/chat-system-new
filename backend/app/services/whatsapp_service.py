import httpx
from app.config import settings

class WhatsAppSendError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, provider_error_code: str | None = None, provider_error_subcode: str | None = None, response_body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_error_code = provider_error_code
        self.provider_error_subcode = provider_error_subcode
        self.response_body = response_body

class WhatsAppService:
    def __init__(self):
        self.base_url = "https://graph.facebook.com"

    async def send_text_message(self, to: str, text: str, token: str = None, phone_id: str = None, api_version: str = None):
        """Sends a text message via WhatsApp Cloud API."""
        # Use provided credentials or fall back to global settings
        token = token or str(settings.WHATSAPP_ACCESS_TOKEN).strip()
        phone_id = phone_id or str(settings.WHATSAPP_PHONE_NUMBER_ID).strip()
        api_version = api_version or settings.META_GRAPH_API_VERSION or "v21.0"

        if not token or not phone_id:
            raise WhatsAppSendError("Credentials missing for WhatsApp send")

        url = f"{self.base_url}/{api_version}/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                body = e.response.text
                err_code = None
                err_subcode = None
                try:
                    payload_json = e.response.json()
                    meta_error = payload_json.get("error") or {}
                    err_code = str(meta_error.get("code")) if meta_error.get("code") is not None else None
                    err_subcode = str(meta_error.get("error_subcode")) if meta_error.get("error_subcode") is not None else None
                except Exception:
                    pass
                raise WhatsAppSendError(
                    "Meta API rejected WhatsApp send",
                    status_code=e.response.status_code,
                    provider_error_code=err_code,
                    provider_error_subcode=err_subcode,
                    response_body=body,
                ) from e
            except Exception as e:
                raise WhatsAppSendError("Unexpected WhatsApp send failure", response_body=str(e)) from e

    async def get_phone_number_id(self, waba_id: str, token: str):
        """Fetches the first phone number ID associated with a WABA."""
        url = f"{self.base_url}/{waba_id}/phone_numbers"
        headers = {"Authorization": f"Bearer {token}"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                if data.get("data"):
                    return data["data"][0].get("id")
                return None
            except Exception as e:
                print(f"[WhatsAppService] Error fetching phone number ID: {e}")
                return None

    async def get_waba_profile(self, waba_id: str, token: str, api_version: str | None = None):
        version = api_version or settings.META_GRAPH_API_VERSION or "v21.0"
        url = f"{self.base_url}/{version}/{waba_id}"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"fields": "name,currency,timezone"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    async def get_phone_number_profile(self, phone_number_id: str, token: str, api_version: str | None = None):
        version = api_version or settings.META_GRAPH_API_VERSION or "v21.0"
        url = f"{self.base_url}/{version}/{phone_number_id}"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"fields": "display_phone_number,verified_name,quality_rating,messaging_limit_tier,code_verification_status"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    async def register_phone_number(self, phone_number_id: str, token: str, api_version: str | None = None):
        version = api_version or settings.META_GRAPH_API_VERSION or "v21.0"
        url = f"{self.base_url}/{version}/{phone_number_id}/register"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload: dict[str, str] = {"messaging_product": "whatsapp"}
        pin = (settings.WHATSAPP_PHONE_REGISTRATION_PIN or "").strip()
        if pin:
            payload["pin"] = pin
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def get_phone_number_operational_profile(self, phone_number_id: str, token: str, api_version: str | None = None):
        version = api_version or settings.META_GRAPH_API_VERSION or "v21.0"
        url = f"{self.base_url}/{version}/{phone_number_id}"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"fields": "id,display_phone_number,verified_name,quality_rating,messaging_limit_tier,code_verification_status,status,platform_type"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

whatsapp_service = WhatsAppService()
