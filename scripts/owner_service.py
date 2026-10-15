"""Owner eligibility: customer archive first, business-scope inference on a miss."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import text

from business_scope_llm import BusinessScopeLLM, PROMPT_VERSION, ScopeAssessmentError

OWNER_POLICY = {
    "version": "一二类业主校验 v2",
    "description": "一二类业主不能属于风机厂、综自厂家、总包方或关联方；三类不校验。",
    "lookup": "以立项时项目业主方全称精确查询客户档案，按大客户分类判断。综自客户按综自厂家、代理商按总包方处理。",
    "fallback": "仅客户档案未查到时查询天眼查，由 LLM 根据经营范围语义判断风机厂、综自厂家或总包方，并返回各类结论和原文依据，页面展示业主基本信息、经营范围与校验结果。经营范围不判断关联方。",
}
RESTRICTED_CATEGORIES = {"风机厂": "风机厂", "综自客户": "综自厂家", "综自厂家": "综自厂家",
                         "代理商": "总包方", "总包方": "总包方", "关联方": "关联方"}


def result(status, owner, source, message, **details):
    return {"status": status, "ownerName": owner, "source": source, "message": message,
            "categories": [], "evidence": [], "policyVersion": OWNER_POLICY["version"], **details}


def archive_result(owner, customers, category_mapping):
    records = []
    categories = []
    unresolved = False
    for row in customers:
        raw = row.get("field0068")
        category_id = str(raw) if raw is not None else None
        label = category_mapping.get(category_id, {}).get("label")
        # Text labels are also accepted if a source returns a resolved dropdown.
        if label is None and category_id in RESTRICTED_CATEGORIES:
            label = category_id
        category = RESTRICTED_CATEGORIES.get(label)
        if category and category not in categories:
            categories.append(category)
        unresolved |= label is None
        records.append({"id": str(row["ID"]), "name": row.get("field0010"),
                        "categoryId": category_id, "categoryLabel": label})
    labels = {r["categoryLabel"] for r in records}
    if categories:
        status = "restricted"
        message = f"业主属于{'、'.join(categories)}，不符合一二类业主要求。"
    elif unresolved or len(labels) > 1:
        status = "review"
        message = "客户档案的大客户分类缺失、编号未映射或同名记录分类不一致，请核实。"
    else:
        status = "clear"
        message = "客户档案的大客户分类未命中受限类别。"
    return result(status, owner, "customer_archive", message,
                  categories=categories, customerRecords=records)


def company_name_key(name):
    """Treat full-width round parentheses as formatting, preserving name text."""
    return name.strip().translate(str.maketrans({"（": "(", "）": ")"}))


class TianyanchaClient:
    def __init__(self, base_url="http://open.api.tianyancha.com", token="", opener=None, classifier=None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = opener or urlopen
        self.classifier = classifier or BusinessScopeLLM()

    @classmethod
    def from_settings(cls, path: Path, classifier=None):
        settings = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return cls(os.environ.get("TIANYANCHA_API_URL", settings.get("apiUrl", "http://open.api.tianyancha.com")),
                   os.environ.get("TIANYANCHA_TOKEN", settings.get("token", "")), classifier=classifier)

    def review(self, owner):
        if not self.token:
            return result("review", owner, "tianyancha", "客户档案未查到该业主，天眼查尚未配置，业主类别待核实。")
        request = Request(self.base_url + "/services/open/ic/baseinfo/normal?" + urlencode({"keyword": owner}),
                          headers={"Authorization": self.token, "Accept": "application/json"})
        try:
            with self.opener(request, timeout=10) as response:
                data = json.load(response)
        except (OSError, URLError, ValueError, UnicodeError):
            return result("review", owner, "tianyancha", "客户档案未查到该业主，天眼查查询失败或超时，业主类别待核实。")
        if not isinstance(data, dict):
            return result("review", owner, "tianyancha", "天眼查返回格式异常，业主类别待核实。")
        if str(data.get("error_code")) != "0":
            message = "天眼查未查到该企业" if str(data.get("error_code")) == "300000" else "天眼查查询未成功"
            return result("review", owner, "tianyancha", message + "，业主类别待核实。",
                          errorCode=str(data.get("error_code")))
        company = data.get("result")
        if not isinstance(company, dict) or not isinstance(company.get("name"), str):
            return result("review", owner, "tianyancha", "天眼查缺少企业信息，业主类别待核实。")
        if company_name_key(company["name"]) != company_name_key(owner):
            return result("review", owner, "tianyancha", "天眼查返回企业名称与业主全称不一致，请核实后重查。",
                          matchedCompanyName=company["name"])
        company_info = {key: company[key] for key in ("legalPersonName", "regCapital", "regStatus", "creditCode")
                        if isinstance(company.get(key), str) and company[key].strip()}
        scope = company.get("businessScope")
        if not isinstance(scope, str) or not scope.strip():
            return result("review", owner, "tianyancha", "天眼查未返回经营范围，业主类别待核实。",
                          companyInfo=company_info, matchedCompanyName=company["name"])
        details = {"businessScope": scope, "matchedCompanyName": company["name"], "companyInfo": company_info,
                   "inferred": True, "classificationMethod": "llm",
                   "model": self.classifier.model, "promptVersion": PROMPT_VERSION,
                   "limitation": "仅根据经营范围由 LLM 判断，不判断关联方；未认定属于不代表已排除全部可能。"}
        try:
            assessments = self.classifier.assess(company["name"], scope)
        except ScopeAssessmentError as error:
            return result("review", owner, "tianyancha", str(error), **details)
        categories = [item["category"] for item in assessments if item["verdict"] == "yes"]
        uncertain = [item["category"] for item in assessments if item["verdict"] == "uncertain"]
        evidence = [{"category": item["category"], "text": quote}
                    for item in assessments if item["verdict"] == "yes" for quote in item["evidence"]]
        if categories:
            status = "restricted"
            message = f"LLM 根据经营范围判断属于{'、'.join(categories)}，不符合一二类业主要求。"
            if uncertain:
                message += f"{'、'.join(uncertain)}仍待核实。"
        elif uncertain:
            status = "review"
            message = f"LLM 无法根据经营范围确定是否属于{'、'.join(uncertain)}，请核实。"
        else:
            status = "clear"
            message = "LLM 根据经营范围未认定属于风机厂、综自厂家或总包方。"
        return result(status, owner, "tianyancha", message, categories=categories,
                      evidence=evidence, assessments=assessments, **details)


def query_owner(connection, owner, category_mapping):
    """None means an actual archive miss, eligible for the external fallback."""
    if not isinstance(owner, str) or not owner.strip():
        return result("review", owner, "ledger", "未填写立项时项目业主方全称，无法校验业主。")
    customers = connection.execute(text(
        "SELECT ID, field0010, field0068 FROM `formmain_4214` "
        "WHERE BINARY `field0010` = BINARY :owner"
    ), {"owner": owner}).mappings().all()
    return archive_result(owner, customers, category_mapping) if customers else None
