export type FieldValue = string | number | null;
export interface Field {
  key: string;
  column: string;
  label: string;
  type: "enum" | "decimal" | "text";
}
export interface Policy {
  id: string;
  name: string;
  description: string;
  fields: Field[];
  checkFields: Field[];
  lookup: Field | null;
  candidateLabel: string;
  scope: string;
}
export interface Policies {
  policies: Policy[];
  ownerPolicy: { description: string; lookup: string; fallback: string };
  stationPolicy: { description: string; lookup: string; scope: string };
}
export interface Project {
  id: string;
  code: string | null;
  name: string;
  displayValues?: Record<string, string | null>;
  [key: string]: FieldValue | Record<string, string | null> | undefined;
}
export interface Dimension extends Field {
  status: "same" | "different" | "missing";
  targetValue: FieldValue;
  candidateValue: FieldValue;
  targetDisplayValue?: string | null;
  candidateDisplayValue?: string | null;
}
export interface Candidate {
  project: Project;
  status: "duplicate" | "review" | "different";
  dimensions: Dimension[];
  issue?: string | null;
}
export interface OwnerReview {
  status:
    | "restricted"
    | "review"
    | "clear"
    | "skipped"
    | "pending"
    | "unavailable";
  ownerName?: string | null;
  matchedCompanyName?: string;
  classificationMethod?: string;
  companyInfo?: Record<string, string>;
  businessScope?: string;
}
export interface StationReview {
  status: "clear" | "warning" | "review" | "pending" | "unavailable";
  fields?: {
    column: string;
    label: string;
    value: string | null;
    displayValue: string | null;
  }[];
  checks?: { rule: string; status: string; message: string }[];
  matches?: { id: string; code: string | null; name: string }[];
  plant?: string | null;
}
export interface ReviewReport {
  status: "clear" | "duplicate" | "review";
  target: Project;
  policy: Policy;
  candidates: Candidate[];
  missing: string[];
  checkedCount: number;
  duplicateCount: number;
  incompleteCount: number;
  reviewReason?: string;
  ownerReview?: OwnerReview;
  stationReview?: StationReview;
}
export interface LookupFailure {
  status: "not_found" | "ambiguous";
  code: string;
}
export type ReviewResponse = ReviewReport | LookupFailure;

export function formatValue(
  field: Pick<Field, "type">,
  value: unknown,
  displayValue?: string | null,
): string {
  if (value === null || value === undefined || String(value).trim() === "")
    return "未填写";
  if (field.type === "enum") return displayValue || `未映射（编号 ${value}）`;
  if (field.type === "decimal")
    return `${String(value)
      .replace(/(\.\d*?)0+$/, "$1")
      .replace(/\.$/, "")} MW`;
  return String(value);
}
