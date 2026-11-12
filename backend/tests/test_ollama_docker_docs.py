"""Ollama-in-Docker setup copy stays aligned across README and getting started."""

from tests.repo_layout import repo_file

_REQUIRED_SNIPPETS = (
    "host.docker.internal:11434",
    "ollama pull",
    "llama3",
    "nomic-embed-text",
    "provider_unreachable",
    "llm_unexpected",
    "extra_hosts",
    "http://localhost:11434",
    "Provider configuration validated",
)


def _assert_ollama_docker_docs(text: str) -> None:
    for snippet in _REQUIRED_SNIPPETS:
        assert snippet in text, f"missing required Ollama Docker doc snippet: {snippet!r}"


def test_readme_documents_ollama_for_dockerized_api():
    text = repo_file("README.md").read_text()
    _assert_ollama_docker_docs(text)


def test_getting_started_documents_ollama_for_dockerized_api():
    text = repo_file("documentation", "content", "getting-started.md").read_text()
    _assert_ollama_docker_docs(text)
