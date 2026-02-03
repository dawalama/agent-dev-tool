"""Configuration management for ADT Command Center."""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def get_adt_home() -> Path:
    """Get the ADT home directory."""
    return Path(os.environ.get("ADT_HOME", Path.home() / ".adt"))


def ensure_adt_home() -> Path:
    """Ensure ADT home directory exists with proper structure."""
    home = get_adt_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "agents").mkdir(exist_ok=True)
    (home / "queue").mkdir(exist_ok=True)
    (home / "logs" / "agents").mkdir(parents=True, exist_ok=True)
    return home


class ProviderConfig(BaseModel):
    """Configuration for an LLM provider."""
    type: str
    api_key: str | None = None
    model: str | None = None
    default: bool = False
    use_for: list[str] = Field(default_factory=list)


class TelegramConfig(BaseModel):
    """Telegram channel configuration."""
    enabled: bool = False
    token: str | None = None
    allowed_users: list[int] = Field(default_factory=list)


class VoiceConfig(BaseModel):
    """Voice channel configuration."""
    enabled: bool = False
    provider: str = "twilio"
    account_sid: str | None = None
    auth_token: str | None = None
    phone_number: str | None = None


class WebConfig(BaseModel):
    """Web dashboard configuration."""
    enabled: bool = True
    port: int = 8421


class ChannelsConfig(BaseModel):
    """Communication channels configuration."""
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    web: WebConfig = Field(default_factory=WebConfig)


class NekoConfig(BaseModel):
    """Neko visual streaming configuration."""
    enabled: bool = False
    image: str = "ghcr.io/m1k1o/neko:firefox"
    port_range: tuple[int, int] = (9000, 9010)


class TerminalConfig(BaseModel):
    """Terminal streaming configuration."""
    enabled: bool = False
    provider: str = "ttyd"
    port_range: tuple[int, int] = (9100, 9110)


class VisualConfig(BaseModel):
    """Visual streaming configuration."""
    neko: NekoConfig = Field(default_factory=NekoConfig)
    terminal: TerminalConfig = Field(default_factory=TerminalConfig)


class EscalationConfig(BaseModel):
    """Escalation rules for agents."""
    stuck_timeout: int = 300  # seconds
    retry_limit: int = 3
    notify_on: list[str] = Field(default_factory=lambda: ["completion", "failure", "blocked"])


class AgentsConfig(BaseModel):
    """Agent orchestration configuration."""
    default_provider: str = "cursor"
    max_concurrent: int = 3
    auto_spawn: bool = False
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)


class ProjectOverride(BaseModel):
    """Per-project configuration overrides."""
    path: Path | None = None
    priority: str = "normal"
    preferred_provider: str | None = None


class TLSConfig(BaseModel):
    """TLS/SSL configuration."""
    enabled: bool = False
    cert_file: str | None = None
    key_file: str | None = None
    

class ServerSettings(BaseModel):
    """Server configuration."""
    host: str = "127.0.0.1"
    port: int = 8420
    secret_key: str | None = None
    tls: TLSConfig = Field(default_factory=TLSConfig)


class Config(BaseModel):
    """Main ADT configuration."""
    server: ServerSettings = Field(default_factory=ServerSettings)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    visual: VisualConfig = Field(default_factory=VisualConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    projects: dict[str, ProjectOverride] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load configuration from file."""
        if path is None:
            path = get_adt_home() / "config.yml"
        
        if not path.exists():
            return cls()
        
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        
        # Resolve environment variables
        data = _resolve_env_vars(data)
        
        return cls.model_validate(data)
    
    def save(self, path: Path | None = None) -> None:
        """Save configuration to file."""
        if path is None:
            path = get_adt_home() / "config.yml"
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w") as f:
            yaml.dump(self.model_dump(mode="json"), f, default_flow_style=False, sort_keys=False)
    
    def get_provider(self, name: str | None = None) -> ProviderConfig | None:
        """Get a provider by name, or the default provider."""
        if name:
            return self.providers.get(name)
        
        # Find default
        for provider in self.providers.values():
            if provider.default:
                return provider
        
        # Return first if no default
        if self.providers:
            return next(iter(self.providers.values()))
        
        return None


def _resolve_env_vars(data: Any) -> Any:
    """Recursively resolve ${VAR} references in config."""
    if isinstance(data, str):
        if data.startswith("${") and data.endswith("}"):
            var_name = data[2:-1]
            return os.environ.get(var_name, "")
        return data
    elif isinstance(data, dict):
        return {k: _resolve_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_resolve_env_vars(v) for v in data]
    return data


def create_default_config() -> Config:
    """Create a default configuration."""
    return Config(
        server=ServerSettings(),
        providers={
            "cursor": ProviderConfig(
                type="cursor-agent",
                default=True,
            ),
            "ollama": ProviderConfig(
                type="ollama",
                model="llama3.2:3b",
                use_for=["quick tasks", "low cost"],
            ),
        },
        channels=ChannelsConfig(
            web=WebConfig(enabled=True),
        ),
        agents=AgentsConfig(
            default_provider="cursor",
            max_concurrent=3,
        ),
    )


def get_default_config_template() -> str:
    """Get the default config file template with comments."""
    return '''# ADT Command Center Configuration
# Environment variables can be referenced as ${VAR_NAME}

server:
  host: "127.0.0.1"
  port: 8420
  # secret_key: ${ADT_SECRET_KEY}

# LLM Providers - agents pick based on task type
# 
# cursor-agent: Uses your existing Cursor authentication (no API key needed)
# anthropic: Requires ANTHROPIC_API_KEY
# ollama: Local, free, no API key needed
#
providers:
  cursor:
    type: cursor-agent
    default: true
    # No API key needed - uses your Cursor login
  
  # claude:
  #   type: anthropic
  #   api_key: ${ANTHROPIC_API_KEY}
  #   model: claude-sonnet-4-20250514
  #   use_for: ["complex reasoning", "architecture"]
  
  # openai:
  #   type: openai
  #   api_key: ${OPENAI_API_KEY}
  #   model: gpt-4o
  #   use_for: ["general tasks"]
  
  # gemini:
  #   type: google
  #   api_key: ${GEMINI_API_KEY}
  #   model: gemini-2.0-flash
  #   use_for: ["large context", "multimodal"]
  
  ollama:
    type: ollama
    model: llama3.2:3b
    # No API key needed - runs locally
    use_for: ["quick tasks", "low cost"]

# Communication Channels
channels:
  telegram:
    enabled: false
    # token: ${TELEGRAM_BOT_TOKEN}
    # allowed_users: [123456789]  # Your Telegram user ID
  
  voice:
    enabled: false
    # provider: twilio
    # account_sid: ${TWILIO_SID}
    # auth_token: ${TWILIO_TOKEN}
    # phone_number: "+1234567890"
  
  web:
    enabled: true
    port: 8421

# Visual Streaming
visual:
  neko:
    enabled: false
    image: "ghcr.io/m1k1o/neko:firefox"
    port_range: [9000, 9010]
  
  terminal:
    enabled: false
    provider: ttyd
    port_range: [9100, 9110]

# Agent Defaults
agents:
  default_provider: cursor
  max_concurrent: 3
  auto_spawn: false
  escalation:
    stuck_timeout: 300  # seconds before escalating
    retry_limit: 3
    notify_on: [completion, failure, blocked]

# Project Overrides (optional - projects are auto-discovered from adt list)
# projects:
#   documaker:
#     priority: high
#     preferred_provider: cursor
'''
