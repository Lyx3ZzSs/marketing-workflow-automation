import { Check, CircleAlert, Minus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  formatValue,
  type OwnerReview,
  type StationReview,
  type ReviewResponse,
  type ReviewReport,
  type Candidate,
  type Policy,
} from "@/lib/review-types";

type Tone = "clear" | "duplicate" | "review" | "neutral";
const tones: Record<Tone, string> = {
  clear: "border-l-primary",
  duplicate: "border-l-[#963f32] bg-[#fff8f5]",
  review: "border-l-[#80601d] bg-[#fffbf2]",
  neutral: "border-l-[#87958b]",
};
const badgeTones: Record<Tone, string> = {
  clear: "bg-primary",
  duplicate: "bg-[#963f32]",
  review: "bg-[#80601d]",
  neutral: "bg-[#657269]",
};

function ResultBadge({
  tone,
  children,
}: {
  tone: Tone;
  children: React.ReactNode;
}) {
  const Icon =
    tone === "clear" ? Check : tone === "neutral" ? Minus : CircleAlert;
  return (
    <Badge
      className={cn(
        "max-w-full gap-2 whitespace-normal rounded-md px-3 py-2 text-sm text-white",
        badgeTones[tone],
      )}
    >
      <Icon className="size-4 shrink-0" />
      {children}
    </Badge>
  );
}

export function OwnerCard({ owner }: { owner?: OwnerReview | null }) {
  const labels = {
    restricted: "业主不符合要求",
    review: "业主待核实",
    clear: "业主未命中受限类别",
    skipped: "业主无需校验（三类项目）",
    pending: "正在校验业主…",
    unavailable: "业主校验未完成",
  };
  const status =
    owner?.status && owner.status in labels ? owner.status : "unavailable";
  const tone: Tone = (
    {
      restricted: "duplicate",
      review: "review",
      clear: "clear",
      skipped: "neutral",
      pending: "neutral",
      unavailable: "review",
    } as const
  )[status];
  const fields = [
    ["legalPersonName", "法定代表人"],
    ["regCapital", "注册资本"],
    ["regStatus", "登记状态"],
    ["creditCode", "统一社会信用代码"],
  ];
  const normalize = (name?: string | null) =>
    (name || "").trim().replaceAll("（", "(").replaceAll("）", ")");
  return (
    <Card
      className={cn("gap-0 border-l-4 shadow-none", tones[tone])}
      aria-label="业主校验结果"
    >
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle>业主校验</CardTitle>
        <ResultBadge tone={tone}>
          {status === "clear" && owner?.classificationMethod === "llm"
            ? "未认定属于受限类别"
            : labels[status]}
        </ResultBadge>
      </CardHeader>
      {!["pending", "unavailable"].includes(status) && (
        <CardContent className="mt-5">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-4 border-t pt-5 text-sm sm:grid-cols-2">
            <div className="sm:col-span-2">
              <dt className="mb-1 text-xs text-muted-foreground">业主名称</dt>
              <dd className="break-words">{owner?.ownerName || "未填写"}</dd>
            </div>
            {owner?.matchedCompanyName &&
              normalize(owner.matchedCompanyName) !==
                normalize(owner.ownerName) && (
                <div className="sm:col-span-2">
                  <dt className="mb-1 text-xs text-muted-foreground">
                    天眼查返回企业名称
                  </dt>
                  <dd>{owner.matchedCompanyName}</dd>
                </div>
              )}
            {fields
              .filter(([key]) => owner?.companyInfo?.[key])
              .map(([key, title]) => (
                <div key={key}>
                  <dt className="mb-1 text-xs text-muted-foreground">
                    {title}
                  </dt>
                  <dd className="break-all">{owner?.companyInfo?.[key]}</dd>
                </div>
              ))}
          </dl>
          <div className="mt-5 border-t pt-4">
            <h4 className="mb-2 text-xs text-muted-foreground">经营范围</h4>
            <p className="whitespace-pre-wrap break-words text-sm leading-8">
              {owner?.businessScope || "暂无经营范围信息"}
            </p>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

export function StationCard({ review }: { review?: StationReview | null }) {
  const labels = {
    clear: "场站分类校验通过",
    warning: "场站分类需核对",
    review: "场站分类待核实",
    pending: "正在校验场站分类…",
    unavailable: "场站分类校验未完成",
  };
  const status =
    review?.status && review.status in labels ? review.status : "unavailable";
  const tone: Tone = (
    {
      clear: "clear",
      warning: "duplicate",
      review: "review",
      pending: "neutral",
      unavailable: "review",
    } as const
  )[status];
  return (
    <Card
      className={cn("gap-0 border-l-4 shadow-none", tones[tone])}
      aria-label="场站类型分类校验结果"
    >
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle>场站类型分类校验</CardTitle>
        <ResultBadge tone={tone}>{labels[status]}</ResultBadge>
      </CardHeader>
      {review?.fields || review?.checks?.length || review?.matches?.length ? (
        <CardContent className="mt-5">
          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            {review.fields?.map((f) => (
              <div key={f.column}>
                <dt className="mb-1 text-xs text-muted-foreground">
                  {f.label}
                </dt>
                <dd className="break-all">
                  {formatValue({ type: "enum" }, f.value, f.displayValue)}
                </dd>
              </div>
            ))}
          </dl>
          {!!review.checks?.length && (
            <ul className="mt-4 list-disc space-y-1 pl-4 text-xs leading-6">
              {review.checks.map((c, i) => (
                <li key={`${c.rule}-${i}`}>{c.message}</li>
              ))}
            </ul>
          )}
          {!!review.matches?.length && (
            <div className="mt-5 border-t pt-4">
              <h4 className="mb-3 text-sm leading-6">
                项目名称与“{review.plant}”完全相同且公司产品子类相同的项目
              </h4>
              {review.matches.map((p) => (
                <article
                  key={p.id}
                  className="mb-3 rounded-md border bg-white p-4"
                >
                  <h4 className="text-sm">{p.name}</h4>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {p.code || "未填写项目编号"}
                  </p>
                  <p className="mt-3 text-xs">公司产品子类一致</p>
                </article>
              ))}
            </div>
          )}
        </CardContent>
      ) : null}
    </Card>
  );
}

function CandidateCard({
  item,
  rule,
  index,
}: {
  item: Candidate;
  rule: Policy;
  index: number;
}) {
  return (
    <article className="border-t py-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold">{item.project.name}</h4>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {item.project.code || "未填写项目编号"}
          </p>
          {rule.lookup && (
            <p className="mt-2 text-xs text-muted-foreground">
              {rule.lookup.label}：
              {String(item.project[rule.lookup.key] ?? "未填写")}
            </p>
          )}
        </div>
        <Badge variant="destructive">
          {rule.checkFields.length}项一致 · 重复
        </Badge>
      </div>
      <div className="my-4 flex flex-wrap gap-2">
        {item.dimensions.map((d) => (
          <Badge key={d.key} variant="secondary">
            {d.label} ·{" "}
            {{ same: "一致", different: "不同", missing: "缺少数据" }[d.status]}
          </Badge>
        ))}
      </div>
      {item.issue && (
        <p className="mb-3 text-xs text-muted-foreground">{item.issue}</p>
      )}
      <details open={index === 0}>
        <summary className="py-2 text-xs text-primary">
          逐项对比项目资料
        </summary>
        <table className="w-full table-fixed text-left text-xs leading-6">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="w-1/4 py-3 font-normal">比对字段</th>
              <th className="py-3 font-normal">当前项目</th>
              <th className="py-3 font-normal">{rule.candidateLabel}</th>
            </tr>
          </thead>
          <tbody>
            {item.dimensions.map((d) => (
              <tr key={d.key} className="border-b">
                <th className="py-3 pr-2 text-muted-foreground font-normal">
                  {d.label}
                </th>
                <td className="break-words py-3 pr-3">
                  {formatValue(d, d.targetValue, d.targetDisplayValue)}
                </td>
                <td className="break-words py-3">
                  {formatValue(d, d.candidateValue, d.candidateDisplayValue)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </article>
  );
}

function DuplicateCard({ report: r }: { report: ReviewReport }) {
  const rule = r.policy;
  const duplicates = r.candidates.filter((c) => c.status === "duplicate");
  const explanation =
    r.reviewReason ||
    (r.status === "duplicate"
      ? `发现 ${r.duplicateCount} 个重复项目。${rule.description}`
      : "存在缺失资料或类别待核实记录，当前无法完整判断是否重复，请核实后重新检查。");
  return (
    <Card
      className={cn("gap-0 border-l-4 shadow-none", tones[r.status])}
      aria-label="查重结果"
    >
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <CardTitle>查重</CardTitle>
          <Badge variant="secondary">{rule.name}</Badge>
        </div>
        <ResultBadge tone={r.status}>
          {
            {
              clear: "未发现重复项目",
              duplicate: "发现重复项目",
              review: "资料待核实",
            }[r.status]
          }
        </ResultBadge>
      </CardHeader>
      <CardContent className="mt-5">
        {r.status !== "clear" && (
          <div className="mb-5 border-y py-4 text-xs leading-7">
            <p>{explanation}</p>
            {!!r.missing.length && (
              <p>当前项目缺少或需核实：{r.missing.join("、")}。</p>
            )}
            {r.incompleteCount > 0 && (
              <p>
                有 {r.incompleteCount} 个{rule.candidateLabel}
                资料或类别不完整，且已知字段未发现差异，需进一步核实。
              </p>
            )}
          </div>
        )}
        <section aria-label="当前项目资料">
          <p className="font-mono text-xs text-muted-foreground">
            {r.target.code}
          </p>
          <h3 className="mt-1 mb-5 font-semibold">{r.target.name}</h3>
          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            {rule.fields.map((f) => (
              <div
                key={f.key}
                className={f.key === rule.lookup?.key ? "sm:col-span-2" : ""}
              >
                <dt className="mb-1 text-xs text-muted-foreground">
                  {f.label}
                </dt>
                <dd className="break-words">
                  {formatValue(
                    f,
                    r.target[f.key],
                    r.target.displayValues?.[f.key],
                  )}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-5 border-t pt-3 text-xs text-muted-foreground">
            枚举选项显示映射名称；未匹配的选项显示编号。
          </p>
        </section>
        {duplicates.length > 0 && (
          <div className="mt-6">
            <h3 className="mb-3 text-sm font-semibold">
              {rule.candidateLabel}{" "}
              <span className="text-muted-foreground">
                / {duplicates.length}
              </span>
            </h3>
            {duplicates.map((c, i) => (
              <CandidateCard
                key={c.project.id}
                item={c}
                rule={rule}
                index={i}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ReviewResults({ report }: { report: ReviewResponse }) {
  if (report.status === "not_found" || report.status === "ambiguous")
    return (
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>
            {report.status === "not_found" ? "项目未找到" : "编号对应多条记录"}
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm leading-7">
          {report.status === "not_found"
            ? `合同台账中未找到“${report.code}”，请核对项目编号。`
            : "该编号对应多条记录，无法确定当前项目，请先核对合同台账。"}
        </CardContent>
      </Card>
    );
  const result = report as ReviewReport;
  return (
    <>
      <OwnerCard owner={result.ownerReview} />
      <StationCard review={result.stationReview} />
      <DuplicateCard report={result} />
    </>
  );
}
