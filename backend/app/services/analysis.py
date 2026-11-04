from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.extracted_clause import ExtractedClause
from app.services.retrieval import retrieval_service
from app.services.cuad_service import cuad_service
from app.services.llm_service import llm_service
import threading
import re

CUAD_CATEGORIES = {
    "Document Name": "Highlight the parts (if any) of this contract related to \"Document Name\" that should be reviewed by a lawyer. Details: The name of the contract",
    "Parties": "Highlight the parts (if any) of this contract related to \"Parties\" that should be reviewed by a lawyer. Details: The two or more parties who signed the contract",
    "Agreement Date": "Highlight the parts (if any) of this contract related to \"Agreement Date\" that should be reviewed by a lawyer. Details: The date of the contract",
    "Effective Date": "Highlight the parts (if any) of this contract related to \"Effective Date\" that should be reviewed by a lawyer. Details: The date when the contract is effective",
    "Expiration Date": "Highlight the parts (if any) of this contract related to \"Expiration Date\" that should be reviewed by a lawyer. Details: On what date will the contract's initial term expire?",
    "Renewal Term": "Highlight the parts (if any) of this contract related to \"Renewal Term\" that should be reviewed by a lawyer. Details: What is the renewal term after the initial term expires?",
    "Notice Period To Terminate Renewal": "Highlight the parts (if any) of this contract related to \"Notice Period To Terminate Renewal\" that should be reviewed by a lawyer. Details: What is the notice period required to terminate renewal?",
    "Governing Law": "Highlight the parts (if any) of this contract related to \"Governing Law\" that should be reviewed by a lawyer. Details: Which state/country's law governs the interpretation of the contract?",
    "Most Favored Nation": "Highlight the parts (if any) of this contract related to \"Most Favored Nation\" that should be reviewed by a lawyer. Details: Is there a clause that if a third party gets better terms?",
    "Non-Compete": "Highlight the parts (if any) of this contract related to \"Non-Compete\" that should be reviewed by a lawyer. Details: Is there a restriction on the ability of a party to compete with the counterparty?",
    "Exclusivity": "Highlight the parts (if any) of this contract related to \"Exclusivity\" that should be reviewed by a lawyer. Details: Is there an exclusive dealing commitment with the counterparty?",
    "No-Solicit Of Customers": "Highlight the parts (if any) of this contract related to \"No-Solicit Of Customers\" that should be reviewed by a lawyer. Details: Is a party restricted from contracting or soliciting customers?",
    "Competitive Restriction Exception": "Highlight the parts (if any) of this contract related to \"Competitive Restriction Exception\" that should be reviewed by a lawyer. Details: This category includes the exceptions or carveouts to Non-Compete, Exclusivity and No-Solicit of Customers above.",
    "No-Solicit Of Employees": "Highlight the parts (if any) of this contract related to \"No-Solicit Of Employees\" that should be reviewed by a lawyer. Details: Is there a restriction on a party's soliciting or hiring employees?",
    "Non-Disparagement": "Highlight the parts (if any) of this contract related to \"Non-Disparagement\" that should be reviewed by a lawyer. Details: Is there a requirement on a party not to disparage the counterparty?",
    "Termination For Convenience": "Highlight the parts (if any) of this contract related to \"Termination For Convenience\" that should be reviewed by a lawyer. Details: Can a party terminate this contract without cause?",
    "Rofr/Rofo/Rofn": "Highlight the parts (if any) of this contract related to \"Rofr/Rofo/Rofn\" that should be reviewed by a lawyer. Details: Is there a clause granting one party a right of first refusal, offer, or negotiation?",
    "Change Of Control": "Highlight the parts (if any) of this contract related to \"Change Of Control\" that should be reviewed by a lawyer. Details: Does one party have the right to terminate or is consent or notice required if such party undergoes a change of control?",
    "Anti-Assignment": "Highlight the parts (if any) of this contract related to \"Anti-Assignment\" that should be reviewed by a lawyer. Details: Is consent or notice required of a party if the contract is assigned to a third party?",
    "Revenue/Profit Sharing": "Highlight the parts (if any) of this contract related to \"Revenue/Profit Sharing\" that should be reviewed by a lawyer. Details: Is one party required to share revenue or profit with the counterparty?",
    "Price Restrictions": "Highlight the parts (if any) of this contract related to \"Price Restrictions\" that should be reviewed by a lawyer. Details: Is there a restriction on the ability of a party to raise or reduce prices?",
    "Minimum Commitment": "Highlight the parts (if any) of this contract related to \"Minimum Commitment\" that should be reviewed by a lawyer. Details: Is there a minimum order size or amount that one party must buy?",
    "Volume Restriction": "Highlight the parts (if any) of this contract related to \"Volume Restriction\" that should be reviewed by a lawyer. Details: Is there a fee increase or consent requirement if use exceeds certain threshold?",
    "Ip Ownership Assignment": "Highlight the parts (if any) of this contract related to \"Ip Ownership Assignment\" that should be reviewed by a lawyer. Details: Does intellectual property created by one party become the property of the counterparty?",
    "Joint Ip Ownership": "Highlight the parts (if any) of this contract related to \"Joint Ip Ownership\" that should be reviewed by a lawyer. Details: Is there any clause providing for joint or shared ownership of intellectual property?",
    "License Grant": "Highlight the parts (if any) of this contract related to \"License Grant\" that should be reviewed by a lawyer. Details: Does the contract contain a license granted by one party to its counterparty?",
    "Non-Transferable License": "Highlight the parts (if any) of this contract related to \"Non-Transferable License\" that should be reviewed by a lawyer. Details: Does the contract limit the ability of a party to transfer the license being granted to a third party?",
    "Affiliate License-Licensor": "Highlight the parts (if any) of this contract related to \"Affiliate License-Licensor\" that should be reviewed by a lawyer. Details: Does the contract contain a license grant by affiliates of the licensor?",
    "Affiliate License-Licensee": "Highlight the parts (if any) of this contract related to \"Affiliate License-Licensee\" that should be reviewed by a lawyer. Details: Does the contract contain a license grant to a licensee and the affiliates of such licensee?",
    "Unlimited/All-You-Can-Eat-License": "Highlight the parts (if any) of this contract related to \"Unlimited/All-You-Can-Eat-License\" that should be reviewed by a lawyer. Details: Is there a clause granting one party an enterprise or unlimited usage license?",
    "Irrevocable Or Perpetual License": "Highlight the parts (if any) of this contract related to \"Irrevocable Or Perpetual License\" that should be reviewed by a lawyer. Details: Does the contract contain a license grant that is irrevocable or perpetual?",
    "Source Code Escrow": "Highlight the parts (if any) of this contract related to \"Source Code Escrow\" that should be reviewed by a lawyer. Details: Is one party required to deposit its source code into escrow?",
    "Post-Termination Services": "Highlight the parts (if any) of this contract related to \"Post-Termination Services\" that should be reviewed by a lawyer. Details: Is a party subject to obligations after the termination of a contract?",
    "Audit Rights": "Highlight the parts (if any) of this contract related to \"Audit Rights\" that should be reviewed by a lawyer. Details: Does a party have the right to audit the books, records, or physical locations of the counterparty?",
    "Uncapped Liability": "Highlight the parts (if any) of this contract related to \"Uncapped Liability\" that should be reviewed by a lawyer. Details: Is a party's liability uncapped upon the breach of its obligation in the contract?",
    "Cap On Liability": "Highlight the parts (if any) of this contract related to \"Cap On Liability\" that should be reviewed by a lawyer. Details: Does the contract include a cap on liability upon the breach of a party's obligation?",
    "Liquidated Damages": "Highlight the parts (if any) of this contract related to \"Liquidated Damages\" that should be reviewed by a lawyer. Details: Does the contract contain a clause that would award either party liquidated damages for breach?",
    "Warranty Duration": "Highlight the parts (if any) of this contract related to \"Warranty Duration\" that should be reviewed by a lawyer. Details: What is the duration of any warranty against defects or errors?",
    "Insurance": "Highlight the parts (if any) of this contract related to \"Insurance\" that should be reviewed by a lawyer. Details: Is there a requirement for insurance that must be maintained by one party for the benefit of the counterparty?",
    "Covenant Not To Sue": "Highlight the parts (if any) of this contract related to \"Covenant Not To Sue\" that should be reviewed by a lawyer. Details: Is a party restricted from contesting the validity of the counterparty's ownership of intellectual property?",
    "Third Party Beneficiary": "Highlight the parts (if any) of this contract related to \"Third Party Beneficiary\" that should be reviewed by a lawyer. Details: Is there a non-contracting party who is a beneficiary to some or all of the clauses in the contract?"
}

class AnalysisService:
    def analyze_document(self, db: Session, document_id: str):
        """
        Analyzes a document against all 41 CUAD legal categories and saves clauses.
        """
        # Ensure we don't duplicate extraction
        existing = db.query(ExtractedClause).filter(ExtractedClause.document_id == document_id).first()
        if existing:
            # Clear old extractions
            db.query(ExtractedClause).filter(ExtractedClause.document_id == document_id).delete()
            db.commit()
            
        extracted = []
        
        for category, question in CUAD_CATEGORIES.items():
            # 1. Use hybrid retrieval to find the top K chunks for this specific legal question
            top_chunks = retrieval_service.hybrid_search(db, document_id, query=category + " " + question, top_k=5)
            
            best_answer = None
            best_chunk = None
            
            for chunk in top_chunks:
                # 2. Extract answer using context-constrained CUAD RoBERTa
                answer_result = cuad_service.extract_answer(question=question, context=chunk.text)
                
                # Check confidence: diff > 0.3 means span is more likely than null CLS answer
                if (
                    answer_result
                    and answer_result.get('score', 0) > 0.25
                    and answer_result.get('diff', 0) > 0.3
                    and answer_result.get('answer', '').strip()
                ):
                    if not best_answer or answer_result['score'] > best_answer['score']:
                        best_answer = answer_result
                        best_chunk = chunk
            
            # 3. Store if we found a valid clause
            if best_answer:
                clause = ExtractedClause(
                    document_id=document_id,
                    chunk_id=best_chunk.id,
                    category=category,
                    extracted_text=best_answer['answer'],
                    page_number=best_chunk.page_number,
                    confidence=best_answer['score']
                )
                db.add(clause)
                extracted.append(clause)
                
        db.commit()
        
        for clause in extracted:
            db.refresh(clause)
            
        return extracted
        
    QUERY_CATEGORY_MAP = {
        "governing law": "Governing Law",
        "jurisdiction": "Governing Law",
        "liability cap": "Cap On Liability",
        "limitation of liability": "Cap On Liability",
        "termination": "Termination For Convenience",
        "terminate": "Termination For Convenience",
        "renewal": "Renewal Term",
        "non-renewal": "Notice Period To Terminate Renewal",
        "audit": "Audit Rights",
        "non-compete": "Non-Compete",
        "solicit": "No-Solicit Of Customers",
        "assignment": "Anti-Assignment",
        "warranty": "Warranty Duration",
        "insurance": "Insurance"
    }

    GENERIC_CONTRACT_WORDS = {
        "what", "is", "the", "of", "in", "to", "a", "an", "are", "was",
        "were", "be", "been", "being", "have", "has", "had", "do", "does",
        "did", "will", "would", "could", "should", "may", "might", "can",
        "shall", "on", "for", "by", "with", "from", "at", "or", "and",
        "not", "this", "that", "it", "its", "as", "who", "which", "there",
        "their", "they", "them", "his", "her", "he", "she", "how", "many",
        "term", "terms", "agreement", "contract", "party", "parties",
        "section", "clause", "provision", "provisions", "herein", "thereof",
        "days", "written", "notice", "effective", "date", "period",
        "obligation", "obligations", "right", "rights", "condition", "conditions",
        "remedy", "remedies", "under", "about", "describe", "specify"
    }

    def query_document(self, db: Session, document_id: str, query: str):
        """
        Queries a specific document and returns a specific answer using RAG + CUAD.
        """
        # 1. Find top K chunks
        top_chunks = retrieval_service.hybrid_search(
            db,
            document_id,
            query=query,
            top_k=5
        )

        if not top_chunks:
            return {
                "answer": "No supporting evidence found in the document.",
                "exact_evidence_text": "",
                "page_numbers": [],
                "supporting_chunk_ids": [],
                "confidence": 0.0
            }

        # Check if category prompt should be used
        cuad_prompt = None
        q_lower = query.lower()
        for phrase, cat in self.QUERY_CATEGORY_MAP.items():
            if phrase in q_lower:
                cuad_prompt = CUAD_CATEGORIES.get(cat)
                break

        best_answer = None
        best_chunk = None

        for chunk in top_chunks:
            prompts = [cuad_prompt, query] if cuad_prompt else [query]
            for p in prompts:
                ans = cuad_service.extract_answer(p, chunk.text)
                if (
                    ans
                    and ans.get("score", 0) > 0.2
                    and ans.get("answer", "").strip()
                    and self._is_cuad_answer_relevant(query, ans["answer"])
                ):
                    if not best_answer or ans["score"] > best_answer["score"]:
                        best_answer = ans
                        best_chunk = chunk

        # Fallback: check if any sentence in top chunks is strictly relevant
        if not best_answer:
            for chunk in top_chunks:
                sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', chunk.text) if s.strip()]
                for s in sentences:
                    if len(s) > 20 and self._is_cuad_answer_relevant(query, s):
                        best_answer = {"answer": s, "score": 0.85}
                        best_chunk = chunk
                        break
                if best_answer:
                    break

        chunks_text = "\n\n".join([chunk.text for chunk in top_chunks])

        if best_answer:
            llm_answer = llm_service.generate_legal_answer(
                query=query, 
                exact_evidence=best_answer["answer"],
                chunks_text=chunks_text
            )
            return {
                "answer": llm_answer,
                "exact_evidence_text": best_answer["answer"],
                "page_numbers": [best_chunk.page_number] if best_chunk.page_number else [],
                "supporting_chunk_ids": [best_chunk.id],
                "confidence": best_answer["score"]
            }

        # If not present in the document, Gemini will explain the absence
        llm_answer = llm_service.generate_legal_answer(
            query=query, 
            exact_evidence="",
            chunks_text=chunks_text
        )
        return {
            "answer": llm_answer,
            "exact_evidence_text": "",
            "page_numbers": [],
            "supporting_chunk_ids": [],
            "confidence": 0.0
        }

    def _is_cuad_answer_relevant(self, query: str, answer: str) -> bool:
        cleaned_query = re.sub(r'[^a-z0-9\s]', ' ', query.lower())
        cleaned_ans = re.sub(r'[^a-z0-9\s]', ' ', answer.lower())

        query_terms = {t for t in cleaned_query.split() if t not in self.GENERIC_CONTRACT_WORDS and len(t) > 2}
        answer_terms = {t for t in cleaned_ans.split() if t not in self.GENERIC_CONTRACT_WORDS and len(t) > 2}

        if not query_terms:
            return True

        # Stem / prefix matching
        overlap = 0
        for qt in query_terms:
            stem = qt[:4] if len(qt) >= 4 else qt
            if any(at.startswith(stem) or stem in at for at in answer_terms):
                overlap += 1

        return overlap >= 1

analysis_service = AnalysisService()
