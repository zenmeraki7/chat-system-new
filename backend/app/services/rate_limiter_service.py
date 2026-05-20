from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.config import settings

logger = logging.getLogger(__name__)

try:
    from redis.asyncio import Redis
except Exception:  # pragma: no cover
    Redis = None  # type: ignore[assignment]


_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last')
local tokens = tonumber(data[1])
local last = tonumber(data[2])

if tokens == nil then tokens = capacity end
if last == nil then last = now end

local delta = math.max(0, now - last)
tokens = math.min(capacity, tokens + (delta * refill))

if tokens >= requested then
  tokens = tokens - requested
  redis.call('HMSET', key, 'tokens', tokens, 'last', now)
  redis.call('EXPIRE', key, 120)
  return {1, 0}
end

local needed = requested - tokens
local wait = math.ceil(needed / refill)
redis.call('HMSET', key, 'tokens', tokens, 'last', now)
redis.call('EXPIRE', key, 120)
return {0, wait}
"""


@dataclass
class LimitSpec:
    key: str
    capacity: int
    refill_per_sec: int


@dataclass
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    blocked_by: str | None = None


class RateLimiterService:
    def __init__(self) -> None:
        self._redis: Redis | None = None
        self._script = None

    async def _get_redis(self) -> Redis | None:
        if not settings.REDIS_URL or Redis is None:
            return None
        if self._redis is None:
            self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    async def _acquire_token_bucket(self, *, spec: LimitSpec, now_ts: float, requested: int = 1) -> tuple[bool, int]:
        redis = await self._get_redis()
        if redis is None:
            # Fail-open when Redis is unavailable/not configured.
            return True, 0
        if self._script is None:
            self._script = redis.register_script(_TOKEN_BUCKET_LUA)
        try:
            result = await self._script(
                keys=[spec.key],
                args=[spec.capacity, spec.refill_per_sec, now_ts, requested],
            )
            allowed = int(result[0]) == 1
            retry_after = int(result[1]) if len(result) > 1 else 0
            return allowed, max(0, retry_after)
        except Exception:
            logger.exception("rate_limiter_redis_error")
            return True, 0

    async def _check_specs(self, specs: Iterable[LimitSpec]) -> RateLimitDecision:
        now_ts = time.time()
        for spec in specs:
            allowed, retry_after = await self._acquire_token_bucket(spec=spec, now_ts=now_ts, requested=1)
            if not allowed:
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=max(1, retry_after),
                    blocked_by=spec.key,
                )
        return RateLimitDecision(allowed=True, retry_after_seconds=0, blocked_by=None)

    async def check_send_limits(
        self,
        *,
        business_id: str,
        phone_number_id: str,
        waba_id: str | None,
        campaign_id: str | None,
        contact_id: str | None,
        is_retry: bool,
        template_category: str | None,
    ) -> RateLimitDecision:
        specs: list[LimitSpec] = [
            LimitSpec(key="rate:global", capacity=max(1, settings.RATE_LIMIT_GLOBAL_MPS), refill_per_sec=max(1, settings.RATE_LIMIT_GLOBAL_MPS)),
            LimitSpec(
                key=f"rate:business:{business_id}",
                capacity=max(1, settings.RATE_LIMIT_BUSINESS_MPS),
                refill_per_sec=max(1, settings.RATE_LIMIT_BUSINESS_MPS),
            ),
            LimitSpec(
                key=f"rate:phone:{phone_number_id}",
                capacity=max(1, settings.RATE_LIMIT_PHONE_MPS),
                refill_per_sec=max(1, settings.RATE_LIMIT_PHONE_MPS),
            ),
        ]
        if waba_id:
            specs.append(
                LimitSpec(
                    key=f"rate:waba:{waba_id}",
                    capacity=max(1, settings.RATE_LIMIT_WABA_MPS),
                    refill_per_sec=max(1, settings.RATE_LIMIT_WABA_MPS),
                )
            )
        if campaign_id:
            specs.append(
                LimitSpec(
                    key=f"rate:campaign:{campaign_id}",
                    capacity=max(1, settings.RATE_LIMIT_CAMPAIGN_MPS),
                    refill_per_sec=max(1, settings.RATE_LIMIT_CAMPAIGN_MPS),
                )
            )
        if is_retry and contact_id:
            specs.append(
                LimitSpec(
                    key=f"rate:recipient_retry:{business_id}:{contact_id}",
                    capacity=max(1, settings.RATE_LIMIT_RECIPIENT_RETRY_MPS),
                    refill_per_sec=max(1, settings.RATE_LIMIT_RECIPIENT_RETRY_MPS),
                )
            )

        decision = await self._check_specs(specs)
        if not decision.allowed:
            return decision

        if (template_category or "").lower() == "marketing" and contact_id:
            daily = await self._check_marketing_frequency(
                business_id=business_id,
                contact_id=contact_id,
            )
            if not daily.allowed:
                return daily

        return RateLimitDecision(allowed=True, retry_after_seconds=0)

    async def _check_marketing_frequency(self, *, business_id: str, contact_id: str) -> RateLimitDecision:
        redis = await self._get_redis()
        if redis is None:
            return RateLimitDecision(allowed=True, retry_after_seconds=0)
        now = datetime.now(timezone.utc)
        day_key = now.strftime("%Y%m%d")
        key = f"rate:marketing_freq:{business_id}:{contact_id}:{day_key}"
        limit = max(1, settings.RATE_LIMIT_MARKETING_PER_CONTACT_PER_DAY)
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, int(math.ceil(24 * 3600)))
            if int(count) > limit:
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=3600,
                    blocked_by=key,
                )
            return RateLimitDecision(allowed=True, retry_after_seconds=0)
        except Exception:
            logger.exception("rate_limiter_marketing_freq_error")
            return RateLimitDecision(allowed=True, retry_after_seconds=0)


rate_limiter_service = RateLimiterService()

