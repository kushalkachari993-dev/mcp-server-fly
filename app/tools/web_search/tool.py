from .service import search_web


def register(mcp):

    @mcp.tool()
    def tavily_search(query: str) -> str:
        """
        Search the web using Tavily.
        Useful for current events, news, and factual queries.
        """

        query = query.strip()

        if not query:
            return "Error: Query cannot be empty"

        data = search_web(query)

        if "error" in data:
            return f"Error: {data['error']}"

        results = data.get("results", [])

        if not results:
            return "No results found."

        formatted_results = []

        for r in results:
            title = r.get("title", "No title")
            content = r.get("content", "No content")
            url = r.get("url", "")

            formatted_results.append(
                f"🔗 {title}\n{content}\n{url}"
            )

        return "\n\n".join(formatted_results)