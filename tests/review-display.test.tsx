import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import {
  OwnerCard,
  StationCard,
  ReviewResults,
} from "../components/review-results";
import {
  formatValue,
  type OwnerReview,
  type StationReview,
  type ReviewReport,
} from "../lib/review-types";

const render = renderToStaticMarkup;
test("owner section remains visible while waiting", () => {
  const html = render(<OwnerCard owner={{ status: "pending" }} />);
  assert.match(html, /aria-label="业主校验结果"/);
  assert.match(html, /正在校验业主/);
  assert.doesNotMatch(html, /业主未命中受限类别/);
});
test("skipped, missing and unknown owner states remain explicit", () => {
  for (const [owner, expected] of [
    [{ status: "skipped" }, "业主无需校验（三类项目）"],
    [null, "业主校验未完成"],
    [{ status: "unknown" }, "业主校验未完成"],
  ] as const) {
    assert.ok(
      render(<OwnerCard owner={owner as OwnerReview | null} />).includes(
        expected,
      ),
    );
  }
});
test("owner results show complete scope and basic information without model analysis", () => {
  for (const [status, expected] of [
    ["clear", "未认定属于受限类别"],
    ["restricted", "业主不符合要求"],
    ["review", "业主待核实"],
  ] as const) {
    const owner = {
      status,
      classificationMethod: "llm",
      ownerName: "详情中的企业",
      message: "详细判断原因",
      model: "test-model",
      businessScope: "经营范围原文",
      companyInfo: {
        legalPersonName: "负责人",
        regCapital: "100万人民币",
        regStatus: "存续",
        creditCode: "CODE123",
      },
    };
    const html = render(<OwnerCard owner={owner} />);
    for (const value of [
      expected,
      "详情中的企业",
      "经营范围原文",
      "负责人",
      "100万人民币",
      "存续",
      "CODE123",
    ])
      assert.ok(html.includes(value));
    assert.doesNotMatch(html, /详细判断原因|test-model/);
  }
});
test("station warnings and project values are safely escaped by React", () => {
  const html = render(
    <StationCard
      review={{
        status: "warning",
        plant: "<电厂>",
        fields: [
          {
            column: "field0185",
            label: "场站类型分类",
            value: "43",
            displayValue: "新签",
          },
        ],
        checks: [
          {
            rule: "new",
            status: "warning",
            message: "发现相同公司产品子类，请核实新签分类。",
          },
        ],
        matches: [{ id: "2", code: "P2", name: "<script>工程</script>" }],
      }}
    />,
  );
  for (const value of [
    "场站分类需核对",
    "发现相同公司产品子类",
    "项目名称与“&lt;电厂&gt;”完全相同",
    "P2",
    "&lt;script&gt;",
  ])
    assert.ok(html.includes(value));
  assert.doesNotMatch(html, /<script>/);
});
test("incomplete station results cannot display pass", () => {
  for (const review of [
    null,
    { status: "pending" },
    {
      status: "review",
      fields: [
        {
          column: "field0020",
          label: "产品类型",
          value: "9000000000000000001",
          displayValue: null,
        },
      ],
    },
  ] as (StationReview | null)[]) {
    const html = render(<StationCard review={review} />);
    assert.match(html, /aria-label="场站类型分类校验结果"/);
    assert.doesNotMatch(html, /校验通过/);
    if (review?.fields)
      assert.match(html, /未映射（编号 9000000000000000001）/);
  }
});
test("only confirmed duplicates are listed and incomplete information remains visible", () => {
  const field = {
    key: "plant",
    column: "field0024",
    label: "电厂名称",
    type: "text" as const,
  };
  const report: ReviewReport = {
    status: "duplicate",
    target: { id: "1", code: "P1", name: "当前项目" },
    policy: {
      id: "class12",
      name: "一二类",
      description: "五项一致",
      fields: [field],
      checkFields: [field],
      lookup: field,
      candidateLabel: "同名电厂项目",
      scope: "全部",
    },
    candidates: ["duplicate", "different", "review"].map((status, i) => ({
      status: status as "duplicate" | "different" | "review",
      project: { id: String(i + 2), code: "P" + i, name: "项目-" + status },
      dimensions: [],
    })),
    missing: [],
    checkedCount: 3,
    duplicateCount: 1,
    incompleteCount: 1,
  };
  const html = render(<ReviewResults report={report} />);
  assert.match(html, /项目-duplicate/);
  assert.doesNotMatch(html, /项目-different|项目-review/);
  assert.match(html, /资料或类别不完整/);
});
test("unknown and ambiguous projects do not show a completed review", () => {
  for (const status of ["not_found", "ambiguous"] as const) {
    const html = render(<ReviewResults report={{ status, code: "<P1>" }} />);
    assert.doesNotMatch(html, /未发现重复项目|校验通过|<P1>/);
  }
});
test("capacity zero, trailing decimals, missing values and long enum IDs remain accurate", () => {
  assert.equal(formatValue({ type: "decimal" }, "0.630000"), "0.63 MW");
  assert.equal(formatValue({ type: "decimal" }, 0), "0 MW");
  assert.equal(formatValue({ type: "text" }, null), "未填写");
  assert.equal(
    formatValue({ type: "enum" }, "9000000000000000001"),
    "未映射（编号 9000000000000000001）",
  );
});
