from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    db_connection_string: Optional[str] = None
    db_connection_string_encrypted: Optional[str] = None
    db_encryption_key: str = "OnSearch-OnS3"

    db_host: Optional[str] = None
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    db_driver: str = "ODBC Driver 17 for SQL Server"
    db_trust_server_certificate: Optional[str] = None

    sap_sl_base_url: Optional[str] = None
    sap_sl_company_db: Optional[str] = None
    sap_sl_username: Optional[str] = None
    sap_sl_password: Optional[str] = None
    sap_sl_verify_ssl: bool = False
    sap_sl_timeout_seconds: int = 30
    sap_sl_location_field: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @staticmethod
    def _normalize_boolean_value(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return "yes"
        if normalized in {"false", "no", "0"}:
            return "no"
        return value.strip()

    def _normalize_connection_string(self, connection_string: str) -> str:
        parts = [part.strip() for part in connection_string.split(";") if part.strip()]
        values = {}
        for part in parts:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            normalized_key = key.strip().lower()
            if normalized_key.startswith("n") and normalized_key[1:] in {
                "data source",
                "server",
                "initial catalog",
                "database",
                "user id",
                "uid",
                "password",
                "pwd",
            }:
                normalized_key = normalized_key[1:]
            values[normalized_key] = value.strip()

        # Already in ODBC format with a driver configured.
        if "driver" in values:
            return connection_string

        server = values.get("server") or values.get("data source")
        database = values.get("database") or values.get("initial catalog")
        user = values.get("uid") or values.get("user id")
        password = values.get("pwd") or values.get("password")
        encrypt = values.get("encrypt") or values.get("encryption")
        if encrypt and encrypt.strip().lower() == "optional":
            encrypt = None
        else:
            encrypt = self._normalize_boolean_value(encrypt)
        trust_server_certificate = (
            values.get("trustservercertificate")
            or values.get("trust server certificate")
            or self.db_trust_server_certificate
        )
        trust_server_certificate = self._normalize_boolean_value(trust_server_certificate)

        if not all([server, database, user, password]):
            return connection_string

        extra_parts = []
        if encrypt:
            extra_parts.append(f"Encrypt={encrypt};")
        if trust_server_certificate:
            extra_parts.append(f"TrustServerCertificate={trust_server_certificate};")

        return (
            f"DRIVER={{{self.db_driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={user};"
            f"PWD={password};"
            f"{''.join(extra_parts)}"
        )

    @property
    def connection_string(self) -> str:
        if self.db_connection_string:
            return self._normalize_connection_string(self.db_connection_string)

        if self.db_connection_string_encrypted:
            raise NotImplementedError(
                "Encrypted DB connection string support requires the original VB.NET Encrypter algorithm."
            )

        required_fields = {
            "DB_HOST": self.db_host,
            "DB_NAME": self.db_name,
            "DB_USER": self.db_user,
            "DB_PASSWORD": self.db_password,
        }
        missing_fields = [field for field, value in required_fields.items() if not value]
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise ValueError(
                f"Database configuration is incomplete. Missing: {missing}. "
                "Set DB_CONNECTION_STRING or the individual DB_* variables."
            )

        return (
            f"DRIVER={{{self.db_driver}}};"
            f"SERVER={self.db_host};"
            f"DATABASE={self.db_name};"
            f"UID={self.db_user};"
            f"PWD={self.db_password};"
        )


settings = Settings()
