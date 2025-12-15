import google.generativeai as genai
from backend.core.config import config

genai.configure(api_key=config.GEN_AI_KEY)


def generate_answer(question: str, context: str):
    prompt = f"""
    Answer the question based ONLY on the context.

    CONTEXT:
    {context}

    QUESTION:
    {question}

    If you cannot answer, say "Not enough information."
    """

    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(prompt)
    return response.text or "No response."
