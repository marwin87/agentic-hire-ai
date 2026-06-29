from src.agents.scout import ScoutAgent
from src.agents.orchestrator import OrchestratorAgent
from src.agents.tailor import TailorAgent
from src.tools.vectordb import CVVectorManager
from src.tools.job_validator import JobValidator
from src.config.settings import config
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr
from typing import Any
from uuid import UUID, uuid4


class AgentFactory:
    """
    Central factory to initialize and provide agents/tools
    with consistent configuration.
    """

    scout: ScoutAgent
    orchestrator: OrchestratorAgent
    tailor: TailorAgent
    job_validator: JobValidator
    vector_manager: CVVectorManager

    def __init__(self, user_id: UUID | None = None) -> None:
        # Use provided user_id or generate a default for MVP single-user mode
        self.user_id = user_id or uuid4()

        # Centralized OpenRouter Config
        api_key: SecretStr | None = config.openrouter_api_key

        # Initialize the shared components
        vision_model = ChatOpenAI(
            model=config.vision_model_name,
            temperature=0,
            base_url=config.openrouter_base_url,
            api_key=api_key,
        )

        embeddings = OpenAIEmbeddings(
            model=config.embedded_model_name,
            base_url=config.openrouter_base_url,
            api_key=api_key,
        )

        # Vector manager initialization with user_id
        self.vector_manager = CVVectorManager(
            vision_model=vision_model,
            embeddings=embeddings,
            user_id=self.user_id,
        )

        scout_llm = ChatOpenAI(
            model=config.scout_model_name,
            temperature=0,
            base_url=config.openrouter_base_url,
            api_key=api_key,
        )

        orchestrator_llm = ChatOpenAI(
            model=config.orchestrator_model_name,
            temperature=0,
            base_url=config.openrouter_base_url,
            api_key=api_key,
        )

        tailor_llm = ChatOpenAI(
            model=config.tailor_model_name,
            temperature=0.7,
            base_url=config.openrouter_base_url,
            api_key=api_key,
        )

        validator_llm = ChatOpenAI(
            model=config.validator_model_name,
            temperature=0,
            base_url=config.openrouter_base_url,
            api_key=api_key,
        )

        # Inject them into the agents and tools
        self.scout = ScoutAgent(llm=scout_llm)
        self.orchestrator = OrchestratorAgent(
            llm=orchestrator_llm,
            vector_manager=self.vector_manager,
            user_id=self.user_id,
        )
        self.tailor = TailorAgent(llm=tailor_llm)
        self.job_validator = JobValidator(llm=validator_llm)


_factory_cache: dict[str, AgentFactory] = {}


def get_agent_factory(user_id: UUID | None = None) -> AgentFactory:
    """Returns a cached AgentFactory instance scoped to the given user_id."""
    cache_key = str(user_id) if user_id else "_default"
    if cache_key not in _factory_cache:
        _factory_cache[cache_key] = AgentFactory(user_id=user_id)
    return _factory_cache[cache_key]
