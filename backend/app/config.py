from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+pymysql://lensguard:lensguard@localhost:3306/lensguard"

    # collector (read-only)
    collector_enabled: bool = True
    collect_interval: int = 30
    kube_context: str | None = None
    ignored_namespaces: str = ""  # comma separated
    log_tail_lines: int = 40

    # rule thresholds
    cpu_alert_pct: float = 85
    mem_alert_pct: float = 85
    restart_threshold: int = 5
    pending_after_seconds: int = 120

    # notifications (all optional)
    notify_min_severity: str = "warning"  # info | warning | critical
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""  # comma separated

    # AI explanations (opt-in)
    openai_enabled: bool = False
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"


settings = Settings()
