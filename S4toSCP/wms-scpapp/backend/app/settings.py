from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_HOST: str
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    DB_DRIVER: str = "ODBC Driver 17 for SQL Server"
    DB_ENCRYPT: str = "no"
    DB_TRUST_SERVER_CERTIFICATE: str = "yes"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    RFID_HOST: str = "0.0.0.0"
    RFID_PORT: int = 5084
    RFID_ANTENNA: int = 1
    RFID_TX_POWER: int = 0

    ZEBRA_PRINTER_IP: str = "0.0.0.0"
    ZEBRA_PRINTER_PORT: int = 9100
    LABEL_TEMPLATE_DIR: str = "label_templates"

    RFID_ANTENNA1_TX_POWER: int = 3000
    RFID_ANTENNA2_TX_POWER: int = 3000
    RFID_ANTENNA3_TX_POWER: int = 3000
    RFID_ANTENNA4_TX_POWER: int = 3000

    RFID_ANTENNA1_RX_SENSITIVITY: int = 0
    RFID_ANTENNA2_RX_SENSITIVITY: int = 0
    RFID_ANTENNA3_RX_SENSITIVITY: int = 0
    RFID_ANTENNA4_RX_SENSITIVITY: int = 0

    RFID_ANTENNA1_ENABLED: int = 1
    RFID_ANTENNA2_ENABLED: int = 0
    RFID_ANTENNA3_ENABLED: int = 0
    RFID_ANTENNA4_ENABLED: int = 0
    RFID_BRIDGE_URL: str = "http://127.0.0.1:8003"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
