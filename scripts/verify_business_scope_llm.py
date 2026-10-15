"""Run the live LLM against confirmed business-scope examples (uses API calls)."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from business_scope_llm import BusinessScopeLLM, PROMPT_VERSION, ScopeAssessmentError

ROOT = Path(__file__).resolve().parent.parent


def main():
    client = BusinessScopeLLM.from_settings(ROOT / "local-data" / "llm.json")
    examples = json.loads((ROOT / "config" / "business_scope_examples.json").read_text())
    # Anonymize the name so passing cannot rely on recognition of these companies.
    def verify(example):
        try:
            assessments = client.assess("待核验企业", example["businessScope"])
            actual = {item["category"]: item["verdict"] for item in assessments}
            passed = all(actual[category] in allowed for category, allowed in example["expected"].items())
            return {"name": example["name"], "passed": passed, "assessments": assessments}
        except ScopeAssessmentError as error:
            return {"name": example["name"], "passed": False, "error": str(error)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(verify, examples))
    print(json.dumps({"model": client.model, "promptVersion": PROMPT_VERSION,
                      "results": results}, ensure_ascii=False, indent=2))
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
