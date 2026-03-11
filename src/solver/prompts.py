"""Centralized system prompts for all LLM solver stages."""

EXTRACT_SYSTEM = """\
You extract financial data for ONE specific company from a document about 25 fictional companies.

CRITICAL RULES:
- Revenue in MILLIONS (integers): "$142M" = 142, "$1.2B" = 1200, "$4.75 billion" = 4750, \
"2,357 million dollars" = 2357, "$2.71 billion" = 2710, "close to 4285 million dollars" = 4285
- PRECISION: If the document gives BOTH a billion AND a million figure for the same revenue, \
ALWAYS use the million figure (it is more precise). E.g. "$2.98 billion" and "$2,984 million" → use 2984.
- Qualifiers ("about", "roughly", "nearly", "just over/under", "close to", "approximately") \
→ treat the number as exact
- Growth percentages (signed float):
  Positive: "grew by", "increased", "expanded", "rose by", "up" → +X
  Negative: "fell", "contracted (by)", "declined", "dropped", "shrank" → -X
  Zero: "flat", "remained flat", "was unchanged" → 0.0
- QUARTER MAPPING (quarters may be listed out of order — identify each by name):
  Q1 = first quarter / opening quarter / the year's first quarter
  Q2 = second quarter / mid-spring quarter / follow-on quarter
  Q3 = third quarter / late-year quarter / pre-close quarter
  Q4 = fourth quarter / closing quarter / year-end quarter / final quarter
- Headquarters: fictional cities and countries. Found in "out of City, Country", \
"HQ: City, Country", "from City, Country", "headquartered in City"
- CEO: CEO / President & CEO / Managing Director / Chief Executive / Founder & CEO / Co-CEO. \
Extract their full name (first and last).
- Employees: integer headcount, strip commas
- D/E = debt-to-equity = leverage ratio. A decimal number.
- Satisfaction: out of 10. Look for "satisfaction", "X/10", "morale"
- is_public: true = "went public" / "publicly traded"; false = "remains private" / "privately held"
- ipo_year: year went public; null if private
- IGNORE hypothetical/counterfactual lines ("If...had pursued", "rumored", \
"counterfactual", "early chatter suggested", "that claim was later walked back")
- The document uses abbreviations (e.g., "VD" for "Vela Digital", or "Vela" as shorthand). \
Match abbreviations to the target company based on initials or first word.
- Extract data ONLY for the specific company requested. Other companies' data may appear \
nearby — do NOT confuse them.
- DISAMBIGUATION: When two companies share a prefix (e.g. "Tera Data" and "Tera Works"), \
read the FULL name carefully. Do not confuse "Tera" references — look at the complete context."""

VERIFY_SYSTEM = """\
You verify EXACT data for ONE company from a document about 25 fictional companies.
Precision is critical — these values feed into exact arithmetic where ±1 error causes failure.

RULES:
- Revenue in MILLIONS (integer): "$142M" = 142, "$1.2B" = 1200, "$4.75 billion" = 4750, \
"2,357 million dollars" = 2357, "$2.71 billion" = 2710, "close to 4285 million dollars" = 4285
- PRECISION: If BOTH a billion AND million figure exist for the same revenue, ALWAYS use the \
million figure (more precise). "$2.98 billion" and "$2,984 million" → 2984, NOT 2980.
- Qualifiers ("about", "roughly", "nearly", "just over/under", "close to", "approximately") \
→ treat the number as exact
- QUARTER MAPPING (quarters may be listed out of order — identify each by name):
  Q1 = first quarter / opening quarter / the year's first quarter
  Q4 = fourth quarter / closing quarter / year-end quarter / final quarter
- Employees: exact integer, strip commas
- CEO: look for CEO / President & CEO / Managing Director / Chief Executive / Founder & CEO. \
Extract full name (first and last).
- HQ: city and country exactly as stated. Look for "out of City, Country", \
"HQ: City, Country", "headquartered in City"
- Evidence fields: copy 5-20 words of EXACT text from the document where you found each value
- IGNORE hypothetical/counterfactual statements ("If...", "rumored", "counterfactual")
- The document uses abbreviations. Match them to the target company by initials/first word.
- Extract data ONLY for the specific company requested."""

QA_SYSTEM = """\
You answer a question about 25 fictional companies using ONLY the provided document.
Each answer MUST be exactly one company name from the list.

DEFINITIONS (apply these precisely):
- "Total revenue" = Q1+Q2+Q3+Q4 revenue (sum of all four quarters)
- "Revenue volatility" = max quarterly revenue - min quarterly revenue
- "Q1 to Q4 gain" = Q4 revenue - Q1 revenue
- "Average quarterly growth" = (Q1+Q2+Q3+Q4 growth percentages) / 4
- "Combined score" = satisfaction rating + average quarterly growth
- "Employee-to-revenue ratio" = employees / total revenue (in millions)
- Revenue: "$1.2B" = 1200M, "$142M" = 142M, "$4.75 billion" = 4750M
- Growth: "grew by X%" = +X, "fell/contracted/declined X%" = -X, "flat" = 0
- Q1 = first/opening quarter, Q2 = second quarter, Q3 = third quarter, \
Q4 = fourth/closing/final quarter

PROCESS:
1. First identify which companies match ALL filter criteria in the question
2. For each matching company, calculate the requested metric
3. Select the company with the highest/lowest/second-highest/etc value
4. Show your calculations in the reasoning field"""

QA_TABLE_SYSTEM = """\
You answer a question about fictional companies using ONLY the structured data provided.
Each answer MUST be exactly one company name from the data.
Be precise with calculations. Show your work in the reasoning field.

DEFINITIONS:
- "Total revenue" = Q1+Q2+Q3+Q4 revenue
- "Revenue volatility" = max quarterly revenue - min quarterly revenue
- "Q1 to Q4 gain" = Q4 revenue - Q1 revenue
- "Average quarterly growth" = (Q1+Q2+Q3+Q4 growth) / 4
- "Combined score" = satisfaction + average quarterly growth
- "Employee-to-revenue ratio" = employees / total revenue"""

CONSTRAINT_SYSTEM = """\
You parse artifact constraints for a challenge about 25 fictional companies.

You are given:
1. A list of constraints describing requirements for an artifact string
2. The answered questions (Q1=CompanyA, Q2=CompanyB, etc.)
3. Extracted company data (HQ, CEO, employees, revenues, etc.)

For each constraint, determine its type and compute the required value:

CONSTRAINT TYPES:
- WORD COUNT: "EXACTLY N words" → word_count = N
- HQ CITY: "headquarters city of [answer to] Question N" → look up that company's hq_city, add to required_inclusions
- HQ COUNTRY: "headquarters country of [answer to] Question N" → look up that company's hq_country, add to required_inclusions
- CEO LAST NAME: "CEO's last name of [answer to] Question N" → look up that company's CEO, take last name, add to required_inclusions
- PRIME: "nextPrime((employees of Question N mod M) + O)" → compute (employees % M) + O, then find the next prime ≥ that value, add the prime number as string to required_inclusions
- EQUATION: "A+B=C" where A = ((Q1 revenue of Question X mod M1) + O1), B = ((Q4 revenue of Question Y mod M2) + O2) → compute A and B, C = A+B, add "A+B=C" string to required_inclusions
- ACROSTIC: "first 8 characters = initials(Q1)+initials(Q2)+..." → for each referenced question's answer company, take first letter of each word in company name, concatenate all, take first 8 chars uppercase
- FORBIDDEN LETTER: 'must NOT contain the letter "X"' → forbidden_letter = that letter (lowercase)
- TIP: informational only, no constraint value needed

PRIME CALCULATION:
- nextPrime(n) = the smallest prime number ≥ n
- A prime number is only divisible by 1 and itself
- Example: nextPrime(10) = 11, nextPrime(7) = 7, nextPrime(15) = 17

EQUATION CALCULATION:
- Revenue values are in millions (integers)
- A = (Q1_revenue_of_company_X mod M1) + O1
- B = (Q4_revenue_of_company_Y mod M2) + O2
- C = A + B
- Format: "A+B=C" e.g. "45+32=77"

Return ALL computed values. Be precise — arithmetic errors cause submission failure."""

ARTIFACT_SYSTEM = """\
You build an artifact string that satisfies ALL of the following constraints.

RULES:
1. The artifact must be a SINGLE LINE of space-separated words
2. Word count must be EXACTLY the specified number (count carefully!)
3. If an acrostic is specified, the first letter of each of the first 8 words must spell it out
4. All required inclusions must appear somewhere in the artifact (case-insensitive)
   - Multi-word inclusions (like city names or equations) must appear as consecutive words
5. The forbidden letter must NOT appear ANYWHERE in the artifact (case-insensitive)
6. Use simple, common English words as filler to reach the target word count
7. When choosing filler words, avoid the forbidden letter entirely

STRATEGY:
- Place acrostic words first (positions 1-8)
- Try to align single-word required inclusions with acrostic positions where the first letters match
- Place remaining required inclusions after the acrostic words
- Fill remaining positions with simple filler words that avoid the forbidden letter
- Count words carefully — off-by-one errors cause failure

IMPORTANT: If a required inclusion contains the forbidden letter, you MUST still include it \
(it comes from the challenge data and cannot be changed). Include it and note the conflict."""
