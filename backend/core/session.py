from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Session:
    """
    Session model for Phase 3 anonymous chat interactions.

    Allows grouping requests without a full user account system.
    """
    id: str
    tenant_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
