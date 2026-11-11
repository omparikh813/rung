Review this claim before it is submitted (or, if it was denied, find what to fix).

Return this JSON object:
{
  "summary": "one plain sentence about the claim's state",
  "ready_to_submit": true or false,
  "issues": [
    {
      "category": "eligibility | prior_auth | code_matching | modifiers | documentation | filing_rules",
      "field": "the exact claim field name, for example modifiers_1",
      "full": "field, why, exact fix, and source",
      "guided": "field and one guiding question, without the fix",
      "minimal": "category and field only",
      "answer": "full explanation, exact fix, and where the fix comes from",
      "suggested_value": "the corrected value, or null if unknown",
      "confidence": "high | low",
      "escalate": true or false
    }
  ],
  "escalate": true or false,
  "escalate_reason": "one sentence, or null"
}

Rules for this task:
- ready_to_submit is true only when issues is empty.
- A passed filing deadline, an invalid member ID, a duplicate, or inactive coverage is
  an issue in its category (filing_rules or eligibility).
- Top level escalate is true if any issue has escalate true.
- If a similar case matches, use its fix and mention it in "answer".
