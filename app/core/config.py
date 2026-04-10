from pydantic import EmailStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── MongoDB Atlas ────────────────────────────────────────────
    # mongodb+srv://gntprsnl_db_user:<password>@cluster0.0qrrq1w.mongodb.net/?appName=Cluster0
    # MONGODB_URI: str = "mongodb+srv://gntprsnl_db_user:uYnfCzedDVhn6QDK@cluster0.0qrrq1w.mongodb.net/?appName=Cluster0&ssl=true&tlsAllowInvalidCertificates=false"
    MONGODB_URI: str = "mongodb+srv://gntprsnl_db_user:claveaqui@cluster0.0qrrq1w.mongodb.net/agraound-nda?retryWrites=true&w=majority"
    MONGODB_DB:  str = "agraound-nda"

    # ── Resend ───────────────────────────────────────────────────
    RESEND_API_KEY:    str = ""
    EMAIL_FROM:        str = "contacto@agraound.site"
    EMAIL_FROM_NAME:   str = "Agraound Consulting"
    EMAIL_PROVIDER_TO: str = "contacto@agraound.site"

    @field_validator("EMAIL_PROVIDER_TO", "EMAIL_FROM")
    @classmethod
    def must_be_valid_email(cls, v: str) -> str:
        if v and "@" not in v:
            raise ValueError(
                f"'{v}' no es un email válido — debe tener formato usuario@dominio.com"
            )
        return v

    # ── App ──────────────────────────────────────────────────────
    # APP_URL se detecta automáticamente desde el request en producción.
    SECRET_KEY:    str = "change-me-in-production"
    MAX_UPLOAD_MB: int = 10
    UPLOAD_DIR:    str = "uploads"

    # ── Cloudflare R2 ────────────────────────────────────────────
    # Token: Dashboard → R2 → Account Details → API Tokens
    #        → Create User API Token → Workers R2 Storage: Edit
    R2_ENDPOINT_URL:      str = ""
    R2_ACCESS_KEY_ID:     str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME:       str = "agraound-docs"
    R2_PRESIGNED_EXPIRY:  int = 3600

    @property
    def r2_enabled(self) -> bool:
        return bool(
            self.R2_ENDPOINT_URL
            and self.R2_ACCESS_KEY_ID
            and self.R2_SECRET_ACCESS_KEY
        )

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
