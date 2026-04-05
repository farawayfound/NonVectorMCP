# Active Context

## Current Focus
- **NLP Optimization:** Refining the deduplication engine (`learn_engine.py`) to balance performance and accuracy. This includes utilizing keyword pre-filtering to minimize expensive spaCy vector computations during the 3rd pass static KB scan.
- **Relevance & Safety:** Improving the RAG chat pipeline with relevance gating (`safeguard.py`). Responses are refused if the highest chunk similarity score doesn't meet the threshold, effectively mitigating LLM hallucinations.
- **Dynamic Suggestions:** Implementing automated generation of chat prompt suggestions based on entities (ORG, PRODUCT) and categories identified by NLP in the user's indexed chunks.

## Recent Changes
- Transitioned semantic similarity caching to use 300-dimension float32 arrays instead of full spaCy `Doc` objects to drastically lower memory usage (53MB vs 2-4GB for 44K chunks).
- Implemented the `chat_documents` endpoint for multi-turn conversational capabilities over user-uploaded documents, maintaining chat history.
- Added automated Jira CSV validation (UTF-8 check, column requirements) to prevent ingestion script failures.

## Outstanding Topics & Next Steps
- Scaling the cross-referencing logic (`cross_reference.py`) as the corpus grows, heavily relying on the optimized vector cache.
- Continuous tuning of `CONTENT_TAGS` and phrase matchers for more accurate domain-specific auto-classification.
- Monitoring the hit rate of the CSV ingestion fallback vs. direct MySQL access for Jira searches (`search_jira`).
