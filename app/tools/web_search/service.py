import os
from tavily import TavilyClient


def get_client():
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise ValueError("TAVILY_API_KEY not set")

    return TavilyClient(api_key=api_key)


def search_web(query: str) -> dict:
    try:
        client = get_client()

        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=5
        )

        return response

    except Exception as e:
        return {"error": str(e)}