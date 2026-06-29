from src.config.settings import config
from typing import List
from pydantic import BaseModel, SecretStr
from langchain_openai import ChatOpenAI
from src.schema.state import JobOffer
from loguru import logger


class JobOfferList(BaseModel):
    """A collection of job offers extracted from search results."""

    offers: List[JobOffer]


class JobParser:
    """
    Specialized parser that takes raw search snippets and
    converts them into structured JobOffer objects.
    """

    def __init__(self, model_name: str | None = None) -> None:
        actual_model = model_name or config.parser_model_name
        api_key: SecretStr | None = config.openrouter_api_key
        self.llm = ChatOpenAI(
            model=actual_model,
            temperature=0,
            base_url=config.openrouter_base_url,
            api_key=api_key,
        )

        self.structured_llm = self.llm.with_structured_output(JobOfferList)

    def parse(self, raw_search_results: str) -> List[JobOffer]:
        """
        Processes raw text and returns a list of JobOffer objects.
        """
        system_prompt = """
        You are an expert Data Extraction Agent.
        Your task is to take raw search engine results and extract structured job posting information.
        If a specific field (like salary) is missing, leave it as 'N/A'.
        Ensure the 'id' is a short, unique string (e.g., 'company-title-hash').
        """

        human_prompt = f"Extract all job postings from these search results:\n\n{raw_search_results}"

        try:
            # The result is automatically an instance of JobOfferList (Pydantic)
            response = self.structured_llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": human_prompt},
                ]
            )
            if isinstance(response, JobOfferList):
                return response.offers
            return []
        except Exception as e:
            logger.error(f"Error during job parsing: {e}")
            return []
