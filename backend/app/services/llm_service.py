import google.generativeai as genai
from app.config import settings

class LLMService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-1.5-pro')
        else:
            self.model = None

    def generate_legal_answer(self, query: str, exact_evidence: str, chunks_text: str) -> str:
        """
        Uses Gemini to synthesize a structured legal answer based strictly on the provided evidence.
        """
        if not self.model:
            return exact_evidence or "LLM integration is not configured. Please add GEMINI_API_KEY to .env."

        system_prompt = f"""You are a legal contract analysis assistant.

Answer the user's question using ONLY the provided contract evidence and verified legal references.

Rules:
- Give a direct answer first.
- Explain the relevant clause in simple language.
- Mention important conditions, exceptions, fees, penalties, or hidden obligations when relevant.
- If a legal Act/Section is provided, explain its relevance briefly.
- Never invent facts, clauses, Acts, or section numbers.
- Do not call something illegal, fraudulent, or a scam unless the evidence clearly establishes it.
- If the evidence is insufficient, say so clearly.
- Do not mention retrieval, embeddings, chunks, JSON, or internal processing.
- Do not output JSON.
- Use concise paragraphs and bullet points only when useful.

USER QUESTION:
{query}

CONTRACT EVIDENCE (Exact Clause):
{exact_evidence}

ADDITIONAL CONTEXT (Surrounding Text):
{chunks_text}
"""

        try:
            response = self.model.generate_content(system_prompt)
            return response.text
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            return exact_evidence or "Error generating response from LLM."

    def generate_web_legal_answer(self, query: str, grounded_context: str) -> str:
        """
        Synthesizes an answer strictly from retrieved web sources.

        Returns an empty string when the LLM is not configured, so the caller
        can fall back to the grounded context instead of inventing content.
        """
        if not self.model or not (grounded_context or "").strip():
            return ""

        system_prompt = f"""You are a legal research assistant answering questions about Indian law.

You are given passages extracted verbatim from verified web sources (official statute and
judgment publishers first, then clearly-labelled secondary commentary).

Rules:
- Use ONLY the passages provided. Never add facts, cases, sections or citations that are not in them.
- Cite the passage number in square brackets, e.g. [1] or [2][3], right after the claim it supports.
- If the passages do not answer the question, say exactly what is missing.
- Prefer official sources; note when a statement comes from secondary commentary.
- Do not mention retrieval, embeddings, reranking, JSON or internal processing.
- Be concise: short paragraphs or bullet points.

QUESTION:
{query}

VERIFIED SOURCES:
{grounded_context}
"""

        try:
            response = self.model.generate_content(system_prompt)
            return response.text or ""
        except Exception as e:
            print(f"Error calling Gemini API for web search: {e}")
            return ""

llm_service = LLMService()
