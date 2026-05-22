from pydantic import BaseModel, ConfigDict


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    user_message: str
    request_id: str
    retryable: bool = False
