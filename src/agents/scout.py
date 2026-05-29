import asyncio
import urllib.parse
import uuid
from datetime import datetime
from typing import Any, List, Optional, Set, cast
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    BaseMessage,
)
from src.schema.state import AgenticHireState, JobOffer
from src.tools.search import job_search_tool
from src.tools.scrape import scrape_webpage_tool
from src.utils import JobParser
from src.utils.progress import emit
from src.config.settings import config
from loguru import logger


class ScoutAgent:
    """
    The ScoutAgent analyzes the candidate's CV and uses OrioSearch
    to find relevant job postings. It also scrapes the found portals to extract
    concrete job offers instead of just search pages.
    """

    def __init__(self, llm: Any) -> None:
        self.llm = llm.bind_tools([job_search_tool, scrape_webpage_tool])
        self.parser = JobParser()

    @staticmethod
    def _normalize_url(url: str) -> str:
        if not url or url == "N/A":
            return url
        parsed = urllib.parse.urlparse(url)
        normalized = urllib.parse.urlunparse(
            (
                parsed.scheme,
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                parsed.params,
                "",
                "",
            )
        )
        return normalized

    async def __call__(
        self, state: AgenticHireState, cv_context: Optional[str] = None
    ) -> dict[str, Any]:
        scout_runs = state.get("scout_runs", 0) + 1
        logger.info(f"--- [NODE] EXECUTING SCOUT AGENT (Run {scout_runs}) ---")
        run_label = f"Run {scout_runs}" if scout_runs > 1 else ""
        await emit(
            "scout",
            f"🔍 Scout starting{' (' + run_label + ')' if run_label else ''}...",
        )

        resume_context = cv_context or state.get(
            "resume_context", "No resume context provided."
        )
        # target_criteria is not in the type definition, fallback correctly
        target_criteria = (
            state.get("target_criteria") or "open job roles matching the candidate's CV"
        )

        # Deduplication state (normalize URLs)
        seen_jobs: Set[str] = {
            self._normalize_url(url) for url in state.get("seen_jobs", [])
        }

        # Extract previously evaluated jobs to avoid duplicates on subsequent runs
        evaluated_jobs = state.get("found_jobs", [])
        rejected_jobs = state.get("rejected_jobs", [])

        all_prior_jobs = evaluated_jobs + rejected_jobs
        titles_to_avoid = [
            job.title for job in all_prior_jobs if hasattr(job, "title") and job.title
        ]
        rejected_urls = {
            self._normalize_url(job.url)
            for job in rejected_jobs
            if hasattr(job, "url") and job.url
        }
        existing_urls = {
            self._normalize_url(job.url)
            for job in evaluated_jobs
            if hasattr(job, "url") and job.url
        }
        urls_to_avoid = existing_urls | rejected_urls | seen_jobs

        logger.debug(
            f"Previously evaluated jobs count: {len(titles_to_avoid)}, seen jobs count: {len(seen_jobs)}"
        )

        # Add a slight variation to the prompt on subsequent runs to encourage new results
        search_variation = ""
        if scout_runs > 1:
            search_variation = f" This is search attempt #{scout_runs}. Try finding different, more recent, or alternative job postings than before."
            if titles_to_avoid or urls_to_avoid:
                search_variation += f"\nIMPORTANT: Skip these previously evaluated/rejected jobs: {', '.join(titles_to_avoid)}. Also avoid any jobs from these URLs: {', '.join(urls_to_avoid)}"
                logger.debug(
                    "Added search variation to avoid previously evaluated jobs."
                )

        current_date = datetime.now().strftime("%Y-%m-%d")

        preferred_portals = config.preferred_job_portals
        portals_list = "\n".join(f"  - {p}" for p in preferred_portals)

        system_msg = SystemMessage(
            content=(
                "You are a professional Recruitment Scout. Your task is to find CONCRETE, ACTIVE job offers, not just search portal pages.\n"
                f"Today's date is {current_date}. Use this to determine if a job posting is old or expired.\n"
                f"PREFERRED PORTALS: Always search these portals first before exploring other sources:\n{portals_list}\n"
                "PRIORITY RULES:\n"
                "1. The “target_criteria” is the PRIMARY source of truth and MUST be strictly followed.\n"
                "2. The CV is SECONDARY and should be used only to refine relevance (skills, experience level, technologies).\n"
                "3. If there is any conflict between the CV and target_criteria, ALWAYS follow the target_criteria.\n"
                "STEPS:\n"
                "Step 1: Use the 'job_search_tool' to find job portals or specific job openings that match the candidate's CV. IMPORTANT: Do NOT restrict your search queries using 'site:' operators (e.g., site:linkedin.com). Search the broader web to find diverse opportunities across all company career pages and job boards.\n"
                "Step 2: Use the 'scrape_webpage_tool' to open URLs found in Step 1. Handle the result based on what it returns:\n"
                "  - If the result contains job content (Title, Company, Description), proceed to Step 3.\n"
                "  - If the result starts with 'JOB_LINKS:' followed by URLs (one per line), it found a listing page — call 'scrape_webpage_tool' on each of those URLs individually to retrieve the actual job content, then proceed to Step 3.\n"
                "  - If the result starts with 'Error:', skip that URL and try the next one.\n"
                "Step 3: IMPORTANT: Check the scraped content of each job offer for signs that it is expired, closed, or no longer accepting applications (e.g., 'offer expired', 'job is closed', 'position filled'). If it is expired, discard it and search for another one.\n"
                "Step 4: Once you have identified valid, active jobs, write a comprehensive final message containing the exact Title, Company, FULL Description, and concrete URL for ONLY the approved active jobs. Do not mention or include discarded jobs in this final summary."
                f"{search_variation}"
            )
        )

        human_msg = HumanMessage(
            content=(
                f"Candidate CV:\n{resume_context}\n\n" f"Preferences: {target_criteria}"
            )
        )

        messages: List[BaseMessage] = [system_msg, human_msg]

        # Pre-seed: run one targeted search per preferred portal so those domains
        # are guaranteed to appear in the conversation regardless of what OrioSearch
        # returns on its own. Injected as synthetic AIMessage+ToolMessage pairs so
        # the LLM sees them as part of its own search history and follows up on any
        # JOB_LINKS: responses in its main loop.
        for portal_url in config.preferred_job_portals:
            domain = urllib.parse.urlparse(portal_url).netloc
            query = f"{target_criteria} {domain}"
            logger.debug(f"[SCOUT] Pre-seeding portal search: {query}")
            await emit("scout", f"Searching {domain}...")
            try:
                tool_call_id = uuid.uuid4().hex
                search_result = await job_search_tool.ainvoke({"query": query})
                messages.append(
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": tool_call_id,
                                "name": "job_search_tool",
                                "args": {"query": query},
                            }
                        ],
                    )
                )
                messages.append(
                    ToolMessage(
                        name="job_search_tool",
                        tool_call_id=tool_call_id,
                        content=str(search_result),
                    )
                )
            except Exception as e:
                logger.warning(f"[SCOUT] Pre-seed search failed for {domain}: {e}")

        all_found_jobs: List[JobOffer] = []

        logger.info(
            f"[SCOUT] Starting LLM interaction loop (max {config.scout_max_iterations} iterations)."
        )
        for i in range(config.scout_max_iterations):
            logger.debug(f"LLM interaction loop iteration {i + 1}")
            response = await self.llm.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls:
                logger.debug("No tool calls made by the LLM. Exiting loop.")
                break

            for tool_call in response.tool_calls:
                tool_name: str | None = None
                tool_id: str | None = None
                try:
                    if not isinstance(tool_call, dict):
                        logger.warning(
                            f"[SCOUT] Unexpected tool_call type: {type(tool_call)}, skipping"
                        )
                        continue

                    tool_name = tool_call.get("name")
                    tool_id = tool_call.get("id")
                    tool_args_raw = tool_call.get("args")

                    if not all([tool_name, tool_id, tool_args_raw]):
                        logger.warning(
                            f"[SCOUT] Incomplete tool_call: name={tool_name}, id={tool_id}, args={tool_args_raw}"
                        )
                        continue

                    tool_args = cast(
                        str | dict[str, Any], tool_args_raw
                    )  # After validation above

                    logger.debug(f"[SCOUT] Executing tool: {tool_name}")

                    if tool_name == "job_search_tool":
                        query_str = (
                            tool_args.get("query", "")
                            if isinstance(tool_args, dict)
                            else str(tool_args)
                        )
                        await emit("scout", f'Searching: "{query_str}"')
                        logger.debug(f"[SCOUT] job_search_tool args: {tool_args}")
                        raw_results = await job_search_tool.ainvoke(tool_args)
                        messages.append(
                            ToolMessage(
                                name="job_search_tool",
                                tool_call_id=cast(str, tool_id),
                                content=str(raw_results),
                            )
                        )
                    elif tool_name == "scrape_webpage_tool":
                        url_str = (
                            tool_args.get("url", "")
                            if isinstance(tool_args, dict)
                            else str(tool_args)
                        )
                        await emit("scout", f"Scraping: {url_str}")
                        logger.debug(f"[SCOUT] scrape_webpage_tool args: {tool_args}")
                        raw_results = await scrape_webpage_tool.ainvoke(tool_args)
                        result_str = str(raw_results)
                        if result_str.startswith("JOB_LINKS:"):
                            n = len(result_str.strip().splitlines()) - 1
                            await emit(
                                "scout",
                                f"  → Found {n} job links, scraping individually...",
                            )
                        elif result_str.startswith("Title:"):
                            await emit("scout", "  → Job offer found ✓")
                        messages.append(
                            ToolMessage(
                                name="scrape_webpage_tool",
                                tool_call_id=cast(str, tool_id),
                                content=result_str,
                            )
                        )
                    await asyncio.sleep(config.scout_rate_limit_delay)
                except Exception as e:
                    logger.error(
                        f"Tool execution failed: {type(e).__name__}: {repr(e)}",
                        exc_info=True,
                    )
                    messages.append(
                        ToolMessage(
                            name=tool_name or "unknown",
                            tool_call_id=tool_id or "unknown",
                            content=f"Error executing tool: {type(e).__name__}",
                        )
                    )

        # Ensure we have a final AI summary if the loop maxed out on tool calls
        if messages and getattr(messages[-1], "type", "") == "tool":
            logger.debug("Forcing final LLM summarization after tool executions.")
            final_response = await self.llm.ainvoke(messages)
            messages.append(final_response)

        logger.info("Parsing found jobs from LLM messages.")
        raw_text_to_parse = ""
        for msg in messages:
            if getattr(msg, "type", "") == "ai" and not getattr(msg, "tool_calls", []):
                if hasattr(msg, "content") and msg.content:
                    content = msg.content
                    if isinstance(content, str):
                        raw_text_to_parse += content + "\n\n"

        if raw_text_to_parse:
            try:
                parsed_jobs = self.parser.parse(raw_text_to_parse)
                all_found_jobs = [
                    job
                    for job in parsed_jobs
                    if not (
                        hasattr(job, "url")
                        and job.url
                        and self._normalize_url(job.url) in urls_to_avoid
                    )
                ]
                logger.debug(f"Parsed {len(all_found_jobs)} jobs from messages.")
            except Exception as e:
                logger.error(
                    f"Parser failed: {type(e).__name__}: {repr(e)}. Continuing with empty results.",
                    exc_info=True,
                )
                all_found_jobs = []

        # Fallback if no tool calls were made or no jobs found
        if not all_found_jobs:
            logger.warning(
                "[SCOUT] No jobs found through agent loop. Running fallback search..."
            )
            try:
                fallback_query = f"{target_criteria} open positions"
                logger.debug(
                    f"[SCOUT] Running fallback search with query: {fallback_query}"
                )
                await asyncio.sleep(config.scout_rate_limit_delay)
                raw_results = await job_search_tool.ainvoke({"query": fallback_query})
                logger.debug(
                    f"[SCOUT] Fallback search returned {len(str(raw_results))} characters"
                )
                parsed_fallback = self.parser.parse(str(raw_results))
                all_found_jobs = [
                    job
                    for job in parsed_fallback
                    if not (
                        hasattr(job, "url")
                        and job.url
                        and self._normalize_url(job.url) in urls_to_avoid
                    )
                ]
                logger.debug(f"Parsed {len(all_found_jobs)} jobs from fallback search.")
            except Exception as e:
                logger.error(
                    f"Fallback search failed: {type(e).__name__}: {repr(e)}",
                    exc_info=True,
                )
                all_found_jobs = []

        # Update seen_jobs with newly found jobs (normalized)
        new_seen = {
            self._normalize_url(job.url)
            for job in all_found_jobs
            if hasattr(job, "url") and job.url
        }
        seen_jobs.update(new_seen)

        logger.info(f"[SCOUT] Found {len(all_found_jobs)} jobs.")
        await emit("scout", f"✓ Found {len(all_found_jobs)} job offer(s)")
        return {
            "found_jobs": all_found_jobs,
            "scout_runs": scout_runs,
            "status": f"Scouted {len(all_found_jobs)} opportunities.",
            "seen_jobs": list(seen_jobs),
        }
