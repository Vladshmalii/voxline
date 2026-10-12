from src.models.telephony import Telephony
from src.repositories.base import CRUD
from src.schemas.telephony import TelephonyConfig


class TelephonyCRUD(CRUD[Telephony]):
    model = Telephony

    @staticmethod
    def build_config(row: Telephony) -> TelephonyConfig:
        """The row as the worker's telephony adapters consume it.

        Args:
            row: A telephony row.

        Returns:
            The plain pydantic binding, validated (an unknown adapter string
            fails here, naming the row, not mid-dial).
        """
        return TelephonyConfig(
            adapter=row.adapter,
            account_id=row.account_id,
            auth_token=row.auth_token,
            caller_id=row.caller_id,
            control_url=row.control_url,
            capabilities=row.capabilities,
            options=row.options,
        )
