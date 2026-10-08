from langchain_core.language_models import BaseChatModel
from langchain_openai import AzureChatOpenAI
from pydantic import SecretStr

from agent_service.config import Settings


def create_model(settings: Settings) -> BaseChatModel:
    """The one place that decides which chat model the agents use."""
    return AzureChatOpenAI(
        azure_endpoint=settings.azure_endpoint,
        api_key=SecretStr(settings.azure_api_key),
        azure_deployment=settings.azure_deployment,
        api_version=settings.azure_api_version,
        temperature=0,
    )
